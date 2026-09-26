"""Finite connected-socket adapter; does not bind sockets or dispatch effects."""

import array
import ctypes
import math
import os
import socket
import sys
import time
from threading import BoundedSemaphore
from uuid import UUID

from auto_g16._managed_offline.common import Rejected, decode_frame, exact, frame


def observed_peer(connection):
    """Observe OS peer identity, never accept a UID from a request."""
    if sys.platform != "darwin" or type(connection) is not socket.socket:
        raise Rejected("BAD_PEER")
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    function = libc.getpeereid
    function.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint))
    function.restype = ctypes.c_int
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    if function(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
        raise Rejected("BAD_PEER")
    return uid.value, gid.value


def _close_received_rights(ancillary):
    failure = None
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            values = array.array("i")
            values.frombytes(data[:len(data) - len(data) % values.itemsize])
            for fd in values:
                try:
                    os.close(fd)
                except OSError as exc:
                    failure = exc
    if failure is not None:
        raise Rejected("BAD_FRAME") from failure


def receive(connection, *, cap, allowed_uid, clock=time.monotonic):
    if type(cap) is not int or cap not in (1024, 16384, 65536):
        raise Rejected("BAD_FRAME")
    uid, _gid = observed_peer(connection)
    if type(allowed_uid) is not int or uid != allowed_uid:
        raise Rejected("BAD_PEER")
    deadline, previous, raw = clock() + 5.0, None, bytearray()
    expected = None
    while True:
        now = clock()
        if not math.isfinite(now) or (previous is not None and now < previous) or now >= deadline:
            raise Rejected("BAD_FRAME")
        previous = now
        connection.settimeout(deadline - now)
        chunk, ancillary, flags, _address = connection.recvmsg(min(65536, cap + 5 - len(raw)), 4096)
        if ancillary or flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC):
            _close_received_rights(ancillary)
            raise Rejected("BAD_FRAME")
        if not chunk:
            return decode_frame(bytes(raw), cap, eof=True), uid
        raw.extend(chunk)
        if len(raw) >= 4 and expected is None:
            expected = int.from_bytes(raw[:4], "big")
            if not 1 <= expected <= cap:
                raise Rejected("BAD_FRAME")
        if expected is not None and len(raw) > expected + 4:
            raise Rejected("BAD_FRAME")


def lifecycle_request(value):
    exact(value, ("protocol", "operation"))
    if value["protocol"] != "auto-g16-managed-lifecycle/1" or value["operation"] not in ("OPEN", "STOP", "STATUS"):
        raise Rejected("BAD_FRAME")
    return value["operation"]


def consumer_request(value):
    exact(value, ("protocol", "operation", "scope"))
    operation = value["operation"]
    fields = {
        "QUERY_LOCAL_STATUS": ("attempt_id",),
        "EXECUTE_APPROVED_ATTEMPT": ("attempt_id", "snapshot_id", "scientific_approval_id",
                                     "batch_submit_approval_id", "operational_confirmation_id"),
    }
    if value["protocol"] != "auto-g16-managed-direct-ipc/1" or operation not in fields:
        # No recovery/collection continuation creation or consumption in V1.
        raise Rejected("SCOPE")
    exact(value["scope"], fields[operation])
    for key, text in value["scope"].items():
        if type(text) is not str or not 1 <= len(text) <= 256 or text != text.strip() or any(not 32 <= ord(c) <= 126 for c in text):
            raise Rejected("SCOPE")
        if key != "attempt_id":
            try:
                parsed = UUID(text)
                if parsed.version != 5 or str(parsed) != text:
                    raise ValueError
            except ValueError as exc:
                raise Rejected("SCOPE") from exc
    return operation


class Admission:
    """No request queue; accepted-socket budgets do not count kernel backlog."""
    def __init__(self, role):
        if role not in ("consumer", "review", "material", "lifecycle"):
            raise Rejected("SCOPE")
        self.role = role
        self.slots = BoundedSemaphore({"consumer": 4, "review": 2, "material": 2, "lifecycle": 1}[role])

    def handle(self, connection, *, uid, handler):
        if not self.slots.acquire(False):
            connection.close()
            raise Rejected("BUSY")
        try:
            cap = {"lifecycle": 1024, "material": 65536, "review": 16384, "consumer": 16384}[self.role]
            value, observed_uid = receive(connection, cap=cap, allowed_uid=uid)
            if self.role == "lifecycle":
                lifecycle_request(value)
                if observed_uid != 0:
                    raise Rejected("BAD_PEER")
            elif self.role == "consumer":
                consumer_request(value)
            # Handler belongs to the trusted composition, never to request data.
            response = handler(value, observed_uid)
            limit = {"consumer": 65536, "material": 65536, "review": 262144, "lifecycle": 4096}[self.role]
            connection.settimeout(5.0)
            connection.sendall(frame(response, limit))
        finally:
            connection.close()
            self.slots.release()
