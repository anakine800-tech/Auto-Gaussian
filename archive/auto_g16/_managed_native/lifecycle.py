"""Single-lifetime G/C/M and durable veto adapters; no second effect ledger."""

from contextlib import contextmanager
import fcntl
import os
import stat
from threading import Event, Lock, get_ident

from auto_g16._managed_offline.common import Rejected, RequestRejected, json_bytes
from auto_g16.transport._direct import _direct_parent


def _identity(value):
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


class DurableVeto:
    """Pinned no-follow state objects. Only qualified composition may create one.

    ACL/import/dependency authenticity is an installation qualification duty;
    these mode/identity checks never claim to replace it.
    """
    def __init__(self, installation):
        self.installation = installation
        self.parent = self.lock = self.marker = None
        self.chain = None
        self._attempted = False

    def establish(self):
        if self._attempted:
            raise Rejected("LIFECYCLE_BLOCKED")
        self._attempted = True
        path = self.installation.state + "/lifecycle"
        with _direct_parent(path + "/lock") as (parent, leaf, chain):
            self.parent = os.dup(parent)
            os.set_inheritable(self.parent, False)
            self.chain = chain
            self.parent_identity = _identity(os.fstat(parent))
            info = os.fstat(parent)
            if info.st_uid != self.installation.executor_uid or stat.S_IMODE(info.st_mode) != 0o700:
                raise Rejected("LIFECYCLE_BLOCKED")
            self.lock = os.open(leaf, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            info = os.fstat(self.lock)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != self.installation.executor_uid or stat.S_IMODE(info.st_mode) != 0o600):
                raise Rejected("LIFECYCLE_BLOCKED")
            self.lock_identity = _identity(info)
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # An existing or partial marker is a permanent veto, never removed.
            self.marker = os.open("lifetime-used", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  0o600, dir_fd=parent)
            self.body = json_bytes({"schema": "auto-g16-managed-lifetime/1",
                                    "installation_sha256": self.installation.description_sha256})
            offset = 0
            while offset < len(self.body):
                count = os.write(self.marker, self.body[offset:])
                if count <= 0:
                    raise Rejected("LIFECYCLE_BLOCKED")
                offset += count
            os.fsync(self.marker)
            os.fsync(self.parent)
            full = getattr(fcntl, "F_FULLFSYNC", None)
            if full is None:
                raise Rejected("LIFECYCLE_BLOCKED")
            fcntl.fcntl(self.marker, full)
            self.marker_identity = _identity(os.fstat(self.marker))
            self.check()

    def check(self):
        if None in (self.parent, self.lock, self.marker) or self.chain is None:
            raise Rejected("LIFECYCLE_BLOCKED")
        with _direct_parent(self.installation.state + "/lifecycle/lock") as (parent, leaf, chain):
            if chain != self.chain or _identity(os.fstat(parent)) != self.parent_identity:
                raise Rejected("LIFECYCLE_BLOCKED")
            for name, fd, expected in ((leaf, self.lock, self.lock_identity),
                                       ("lifetime-used", self.marker, self.marker_identity)):
                opened = os.fstat(fd)
                if (_identity(opened) != expected or opened.st_nlink != 1
                        or _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected):
                    raise Rejected("LIFECYCLE_BLOCKED")
            if os.pread(self.marker, len(self.body) + 1, 0) != self.body:
                raise Rejected("LIFECYCLE_BLOCKED")


class Lifecycle:
    def __init__(self, installation, veto):
        self.installation, self.veto = installation, veto
        self.c, self.m = Lock(), Lock()
        self._poisoned = Event()
        self._state, self.owner = "BLOCKED", None
        self._registry_created = False
        self.children = []
        self._binding = (installation, veto, self.c, self.m, self.children)
        try:
            veto.establish()
            self._state = "READY_CLOSED"
        except BaseException:
            self.poison()
            raise

    @property
    def state(self):
        return "BLOCKED" if self._poisoned.is_set() else self._state

    def poison(self):
        self._poisoned.set()

    def _integrity(self):
        if any(a is not b for a, b in zip(self._binding, (self.installation, self.veto, self.c, self.m, self.children))):
            self.poison()
            raise Rejected("LIFECYCLE_BLOCKED")
        try:
            self.veto.check()
        except BaseException:
            self.poison()
            raise

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
                self._state = "OPEN"
            elif operation == "STOP" and self.state in ("READY_CLOSED", "OPEN"):
                self._state = "STOPPED"
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
        except BaseException as exc:
            # Only the three audited request sites carry this exact marker.
            # Generic SCOPE/EXPIRED errors and unknown classifications still
            # poison. Never clear an earlier veto from an original owner.
            if (readonly and type(exc) is RequestRejected and type(exc.reason) is str
                    and exc.reason in {"EXPIRED", "UNKNOWN_VIEW", "SCOPE"}):
                self._integrity()
            else:
                self.poison()
            raise
        finally:
            self.owner = None
            self.c.release()

    def launch(self, supervisor, request, operation, recheck):
        """Caller retains original owner guard inside C; no ticket escapes M."""
        if self.owner != get_ident() or not self.m.acquire(False):
            raise Rejected("BUSY")
        try:
            self._integrity()
            if self.state != "OPEN":
                raise Rejected("LIFECYCLE_BLOCKED")
            recheck()
            # Retain the owner even when creation/registration becomes uncertain.
            self.children.append(supervisor)
            supervisor.start(request, operation)
            return supervisor
        except BaseException:
            self.poison()
            raise
        finally:
            self.m.release()
