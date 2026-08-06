#!/usr/bin/env python3
"""Fixed clean-exec child for trusted server-local session composition.

This entrypoint accepts only the parent's private control socket, its own
already-open source descriptor, the already-open session source descriptor,
and the owner-bound scripts directory.  It accepts no command, environment,
root, state, transport, or working-directory override.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import stat
import struct
import sys
import types
from pathlib import Path
from typing import Any


PROTOCOL = "auto-g16-direct-trusted-session-clean-exec/1"
CHILD_FLAG = "--auto-g16-direct-trusted-session-clean-exec-child"
MAX_FRAME_BYTES = 32 * 1024 * 1024
FIXED_ENVIRONMENT = {"LANG": "C", "LC_ALL": "C"}
FIXED_CWD = "/"
ARTIFACT_FIELDS = (
    "profile_policy",
    "stable_evidence",
    "profile",
    "authorization",
    "transport_profile",
    "ssh_system_policy_evidence",
    "pbs_script",
    "pbs_review",
    "input_bytes",
    "resource_ledger",
    "resource_policy",
    "resource_gate",
    "scheduler_snapshot",
    "live_approval",
)


class FixedCleanExecError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FixedCleanExecError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _read_source(descriptor: int, label: str) -> tuple[bytes, tuple[int, ...]]:
    before = os.fstat(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(descriptor)
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_uid,
        before.st_gid,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    _require(
        stat.S_ISREG(before.st_mode)
        and identity
        == (
            after.st_dev,
            after.st_ino,
            after.st_uid,
            after.st_gid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        f"{label} source identity differs",
    )
    return b"".join(chunks), identity


def _recv_exact(control: socket.socket, size: int) -> bytes:
    _require(type(size) is int and 0 <= size <= MAX_FRAME_BYTES, "frame size differs")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = control.recv(remaining)
        _require(bool(chunk), "control socket closed during a frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(control: socket.socket) -> dict[str, Any]:
    header = _recv_exact(control, 4)
    size = struct.unpack("!I", header)[0]
    _require(0 < size <= MAX_FRAME_BYTES, "request frame size differs")
    raw = _recv_exact(control, size)
    value = json.loads(raw.decode("utf-8"))
    _require(
        type(value) is dict and _canonical_bytes(value) == raw,
        "request must be canonical JSON",
    )
    return value


def _send_frame(control: socket.socket, value: dict[str, Any]) -> None:
    payload = _canonical_bytes(value)
    _require(0 < len(payload) <= MAX_FRAME_BYTES, "response frame size differs")
    control.sendall(struct.pack("!I", len(payload)) + payload)


def _decode_artifacts(value: dict[str, Any], session: types.ModuleType) -> Any:
    _require(
        set(value) == {"protocol", "artifacts"}
        and value["protocol"] == PROTOCOL
        and type(value["artifacts"]) is dict
        and tuple(sorted(value["artifacts"])) == tuple(sorted(ARTIFACT_FIELDS)),
        "artifact request fields differ",
    )
    decoded: dict[str, bytes] = {}
    for field in ARTIFACT_FIELDS:
        encoded = value["artifacts"][field]
        _require(type(encoded) is str and bool(encoded), f"{field} encoding differs")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise FixedCleanExecError(f"{field} encoding differs") from exc
        _require(bool(raw), f"{field} must be non-empty")
        decoded[field] = raw
    return session.DirectServerSessionArtifacts(**decoded)


def _run_child(
    control_descriptor: int,
    helper_source_descriptor: int,
    session_source_descriptor: int,
    channel_source_descriptor: int,
    w5_source_descriptor: int,
    executable_descriptor: int,
    scripts_directory: str,
) -> int:
    control = socket.socket(fileno=control_descriptor)
    control.settimeout(5.0)
    try:
        helper_raw, helper_identity = _read_source(helper_source_descriptor, "helper")
        session_raw, session_identity = _read_source(session_source_descriptor, "session")
        channel_raw, channel_identity = _read_source(channel_source_descriptor, "shared channel")
        w5_raw, w5_identity = _read_source(w5_source_descriptor, "W5")
        os.close(helper_source_descriptor)
        helper_source_descriptor = -1
        os.close(session_source_descriptor)
        session_source_descriptor = -1
        os.close(channel_source_descriptor)
        channel_source_descriptor = -1
        os.close(w5_source_descriptor)
        w5_source_descriptor = -1
        os.close(executable_descriptor)
        executable_descriptor = -1

        scripts = Path(scripts_directory)
        _require(
            scripts.is_absolute()
            and scripts.is_dir()
            and not scripts.is_symlink()
            and os.getcwd() == FIXED_CWD
            and dict(os.environ) == FIXED_ENVIRONMENT,
            "clean-exec cwd or environment differs",
        )
        sys.path.insert(0, str(scripts))
        module = types.ModuleType("direct_trusted_session_composition")
        module.__file__ = str(scripts / "direct_trusted_session_composition.py")
        module.__package__ = ""
        sys.modules[module.__name__] = module
        exec(compile(session_raw, module.__file__, "exec"), module.__dict__)
        channel = types.ModuleType("direct_shared_fixed_ssh_channel")
        channel.__file__ = str(scripts / "direct_shared_fixed_ssh_channel.py")
        channel.__package__ = ""
        channel.__reviewed_source_sha256__ = hashlib.sha256(channel_raw).hexdigest()
        sys.modules[channel.__name__] = channel
        exec(compile(channel_raw, channel.__file__, "exec"), channel.__dict__)
        w5 = types.ModuleType("direct_one_hop_transport")
        w5.__file__ = str(scripts / "direct_one_hop_transport.py")
        w5.__package__ = ""
        w5.__reviewed_source_sha256__ = hashlib.sha256(w5_raw).hexdigest()
        sys.modules[w5.__name__] = w5
        exec(compile(w5_raw, w5.__file__, "exec"), w5.__dict__)

        attestation = module._activate_fixed_clean_exec_child(
            control_descriptor=control_descriptor,
            helper_source_sha256=hashlib.sha256(helper_raw).hexdigest(),
            helper_source_identity=helper_identity,
            session_source_sha256=hashlib.sha256(session_raw).hexdigest(),
            session_source_identity=session_identity,
            channel_source_sha256=hashlib.sha256(channel_raw).hexdigest(),
            channel_source_identity=channel_identity,
            w5_source_sha256=hashlib.sha256(w5_raw).hexdigest(),
            w5_source_identity=w5_identity,
            scripts_directory=scripts_directory,
            original_argv=tuple(sys.argv),
        )
        _send_frame(control, attestation)
        try:
            request = _recv_frame(control)
        except FixedCleanExecError as exc:
            if str(exc) == "control socket closed during a frame":
                return 0
            raise
        artifacts = _decode_artifacts(request, module)
        capability = (
            module.FixedTrustedServerLocalSessionOwner.production()
            .compose_once(artifacts)
        )
        capability.assert_current()
        readiness = module._session_ready_document(capability)
        _send_frame(
            control,
            {
                "protocol": PROTOCOL,
                "status": "ready_for_w5",
                "readiness": readiness,
            },
        )
        control.settimeout(None)
        try:
            transition = _recv_frame(control)
            w5_lease, ack = module._consume_fixed_child_w5_transition_once(
                capability,
                readiness,
                transition,
            )
            w5_lease.assert_current()
            _send_frame(control, ack)
        except BaseException:
            module._retire_session_unknown_once(
                capability,
                "fixed-clean-exec-w5-transition-failed",
            )
            try:
                _send_frame(
                    control,
                    {
                        "protocol": PROTOCOL,
                        "status": "rejected",
                        "error": "FixedW5TransitionError",
                    },
                )
            except BaseException:
                pass
            return 3
        try:
            operation = _recv_frame(control)
        except FixedCleanExecError as exc:
            if str(exc) == "control socket closed during a frame":
                module._retire_session_unknown_once(
                    capability,
                    "fixed-clean-exec-parent-control-eof-after-w5-lease",
                )
                return 3
            module._retire_session_unknown_once(
                capability,
                "fixed-clean-exec-malformed-frame-after-w5-lease",
            )
            return 3
        seam = None
        try:
            expected_operation = {
                "protocol": PROTOCOL,
                "operation": "submit_once",
                "session_id": readiness["session_id"],
                "readiness_payload_sha256": readiness["result_payload_sha256"],
            }
            module._require(operation == expected_operation, "fixed W5 operation frame differs")
            seam = module.consume_w5_operation_seam_once(w5_lease)
            receipt = w5.consume_production_once(seam)
            result = receipt.portable_projection()
            _send_frame(
                control,
                {"protocol": PROTOCOL, "status": "completed", "result": result},
            )
            return 0
        except BaseException:
            if seam is None:
                module._retire_session_unknown_once(
                    capability,
                    "fixed-clean-exec-w5-operation-unknown",
                )
            try:
                _send_frame(
                    control,
                    {"protocol": PROTOCOL, "status": "submission_uncertain"},
                )
            except BaseException:
                pass
            return 3
    except BaseException as exc:
        try:
            _send_frame(
                control,
                {"protocol": PROTOCOL, "status": "rejected", "error": type(exc).__name__},
            )
        except BaseException:
            pass
        return 2
    finally:
        for descriptor in (helper_source_descriptor, session_source_descriptor, channel_source_descriptor, w5_source_descriptor, executable_descriptor):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        control.close()


def main(argv: list[str] | None = None) -> int:
    if __name__ != "__main__":
        return 64
    values = sys.argv[1:] if argv is None else argv
    if (
        type(values) is not list
        or len(values) != 8
        or values[0] != CHILD_FLAG
        or any(not item.isascii() or not item.isdigit() for item in values[1:7])
    ):
        return 64
    control_descriptor, helper_descriptor, session_descriptor, channel_descriptor, w5_descriptor, executable_descriptor = (
        int(item, 10) for item in values[1:7]
    )
    if (
        min(control_descriptor, helper_descriptor, session_descriptor, channel_descriptor, w5_descriptor, executable_descriptor) < 3
        or len({control_descriptor, helper_descriptor, session_descriptor, channel_descriptor, w5_descriptor, executable_descriptor}) != 6
    ):
        return 64
    return _run_child(
        control_descriptor,
        helper_descriptor,
        session_descriptor,
        channel_descriptor,
        w5_descriptor,
        executable_descriptor,
        values[7],
    )


if __name__ == "__main__":
    raise SystemExit(main())
