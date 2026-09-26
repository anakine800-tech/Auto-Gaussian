"""Data/call-boundary tests only. No actual sockets, children or permissions."""

import array
import socket
import unittest
from unittest.mock import patch

from auto_g16._managed_native import ipc
from auto_g16._managed_native.darwin import DarwinOwner
from auto_g16._managed_native.installation import parse_description, require_qualified_installation
from auto_g16._managed_native.service import run_direct
from auto_g16._managed_offline.common import Rejected, frame, json_bytes
from auto_g16.transport._canonical import TransportBoundaryError


class Connection:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.deadlines = []
    def settimeout(self, value): self.deadlines.append(value)
    def recvmsg(self, size, ancillary): return self.chunks.pop(0)


class BoundaryTests(unittest.TestCase):
    def description(self, **changes):
        value = {"schema": "auto-g16-managed-installation-description/1", "installation_id": "candidate-v1",
                 "executor_uid": 701, "desktop_uid": 501}
        value.update(changes)
        return json_bytes(value)

    def test_description_derives_immutable_template_paths(self):
        value = parse_description(self.description())
        self.assertEqual(value.state, "/private/var/db/auto-g16/candidate-v1")
        self.assertEqual(value.root, "/Library/AutoG16/installations/candidate-v1")
        self.assertLess(len(value.ipc + "/review.sock"), 104)

    def test_description_rejects_untrusted_activation_and_paths(self):
        for values in ({"qualified": True}, {"path": "/tmp/installation"}, {"executor_uid": 0},
                       {"executor_uid": 501}, {"executor_uid": True}, {"installation_id": "../x"},
                       {"installation_id": "current/x"}, {"environment": {}}, {"argv": []}):
            with self.subTest(values=values), self.assertRaises(Rejected):
                parse_description(self.description(**values))

    def test_noncanonical_and_duplicate_json_rejected(self):
        for raw in (b'{}', self.description() + b'\n', b'{"schema":"x","schema":"x"}'):
            with self.subTest(raw=raw), self.assertRaises(Rejected): parse_description(raw)

    def test_production_closed_before_native_library_or_io(self):
        with patch("ctypes.CDLL", side_effect=AssertionError("native library loaded")), patch("os.open", side_effect=AssertionError("filesystem opened")):
            with self.assertRaises(Rejected): require_qualified_installation()
            with self.assertRaises(Rejected): DarwinOwner(None, None, None, None)
            with self.assertRaises(TransportBoundaryError): run_direct(None, None)

    def test_complete_frame_requires_eof_and_observed_peer(self):
        value = {"protocol": "auto-g16-managed-lifecycle/1", "operation": "STATUS"}
        wire = frame(value, 1024)
        connection = Connection([(wire[:3], [], 0, None), (wire[3:], [], 0, None), (b"", [], 0, None)])
        with patch.object(ipc, "observed_peer", return_value=(0, 0)):
            result, uid = ipc.receive(connection, cap=1024, allowed_uid=0)
        self.assertEqual((result, uid), (value, 0))
        self.assertTrue(all(0 < deadline <= 5 for deadline in connection.deadlines))

    def test_bad_peer_before_read(self):
        connection = Connection([])
        with patch.object(ipc, "observed_peer", return_value=(501, 20)), self.assertRaisesRegex(Rejected, "BAD_PEER"):
            ipc.receive(connection, cap=1024, allowed_uid=0)
        self.assertEqual(connection.deadlines, [])

    def test_ancillary_rights_closed_before_rejection(self):
        ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [73, 74]).tobytes())]
        connection = Connection([(b"x", ancillary, 0, None)])
        with patch.object(ipc, "observed_peer", return_value=(0, 0)), patch.object(ipc.os, "close") as close:
            with self.assertRaises(Rejected): ipc.receive(connection, cap=1024, allowed_uid=0)
            self.assertEqual([call.args[0] for call in close.call_args_list], [73, 74])

    def test_extra_frame_truncation_and_short_eof_rejected(self):
        wire = frame({"a": "b"}, 1024)
        for chunks in ([(wire + b"x", [], 0, None)], [(wire, [], socket.MSG_CTRUNC, None)],
                       [(wire[:-1], [], 0, None), (b"", [], 0, None)]):
            with self.subTest(chunks=chunks), patch.object(ipc, "observed_peer", return_value=(0, 0)), self.assertRaises(Rejected):
                ipc.receive(Connection(chunks), cap=1024, allowed_uid=0)

    def test_admin_request_has_no_path_pid_or_reset(self):
        for value in ({"protocol": "auto-g16-managed-lifecycle/1", "operation": "RESET"},
                      {"protocol": "auto-g16-managed-lifecycle/1", "operation": "OPEN", "pid": 37}):
            with self.assertRaises(Rejected): ipc.lifecycle_request(value)

    def test_consumer_cannot_upload_authority_or_continue(self):
        base = {"protocol": "auto-g16-managed-direct-ipc/1", "operation": "QUERY_LOCAL_STATUS", "scope": {"attempt_id": "a"}}
        self.assertEqual(ipc.consumer_request(base), "QUERY_LOCAL_STATUS")
        for value in ({**base, "approved": True}, {**base, "operation": "COLLECT_APPROVED_EPOCH"},
                      {**base, "operation": "RECONCILE_EXACT_JOB"}, {**base, "scope": {"attempt_id": "a", "path": "/tmp"}}):
            with self.assertRaises(Rejected): ipc.consumer_request(value)

    def test_material_admission_uses_exact_larger_cap_and_does_not_replay_reply_failure(self):
        from unittest.mock import Mock
        admission = ipc.Admission("material")
        connection = Mock()
        connection.sendall.side_effect = BrokenPipeError("reply lost")
        handler = Mock(return_value={"status":"PREPARED_LOCAL_ONLY"})
        with patch.object(ipc, "receive", return_value=({"operation":"PREPARE_LOCAL"},501)) as receive:
            with self.assertRaises(BrokenPipeError): admission.handle(connection, uid=501, handler=handler)
            receive.assert_called_once_with(connection, cap=65536, allowed_uid=501)
        handler.assert_called_once()
        connection.close.assert_called_once()
        self.assertTrue(admission.slots.acquire(False))
        admission.slots.release()

    def test_material_receiver_rejects_one_byte_over_cap(self):
        connection = Connection([((65537).to_bytes(4,"big"), [], 0, None)])
        with patch.object(ipc, "observed_peer", return_value=(501,20)), self.assertRaises(Rejected):
            ipc.receive(connection, cap=65536, allowed_uid=501)
