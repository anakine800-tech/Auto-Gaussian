#!/usr/bin/env python3
"""Fixed process-isolated descriptor-relative directory mutation helper.

This file is the child entrypoint.  It accepts no root, path, command, label,
environment, shell, transport, retry, cleanup, rename, or deletion override.
The parent supplies one private control socket; reviewed directory descriptors
arrive only through ``SCM_RIGHTS`` after this clean interpreter has exec'd.
"""

from __future__ import annotations

import array
import fcntl
import hashlib
import json
import os
import socket
import stat
import struct
import sys
from typing import Any


PROTOCOL = "auto-g16-direct-root-fixed-helper/1"
CHILD_FLAG = "--auto-g16-fixed-helper-child"
SCRATCH_LABEL = "scratch"
MAX_FRAME_BYTES = 65536
MAX_DESCRIPTOR_COUNT = 65
FIXED_SOCKET_TIMEOUT_SECONDS = 5.0
READY = {
    "protocol": PROTOCOL,
    "state": "ready_no_descriptors_no_effect",
    "unrelated_fd_count": 0,
}
VALIDATED = {
    "protocol": PROTOCOL,
    "state": "validated_no_effect",
    "received_fds_close_on_exec": True,
}
PROJECT_CREATED = {"protocol": PROTOCOL, "state": "project_created_outcome_uncertain"}
COMPLETED = {
    "protocol": PROTOCOL,
    "state": "completed",
    "operations_completed": [
        "create_project_directory_exclusive",
        "create_scratch_directory_exclusive",
    ],
}
SESSION_HANDOFF_COMMAND = "continue_scratch_and_handoff"
SESSION_COMPLETED_STATE = "completed_project_fd_handoff"


class FixedHelperError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FixedHelperError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _strict_frame(raw: bytes, label: str) -> dict[str, Any]:
    _require(
        type(raw) is bytes and 0 < len(raw) <= MAX_FRAME_BYTES,
        f"{label} frame size differs",
    )

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            _require(type(key) is str and key not in value, f"{label} repeats a key")
            value[key] = item
        return value

    def reject_number(token: str) -> Any:
        raise FixedHelperError(f"{label} contains a non-integer number: {token}")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixedHelperError(f"{label} is not strict UTF-8 JSON") from exc
    _require(type(value) is dict, f"{label} must be an exact object")
    _require(_canonical_bytes(value) == raw, f"{label} is not canonical JSON")
    return value


def _send_frame(control: socket.socket, value: dict[str, Any]) -> None:
    payload = _canonical_bytes(value)
    _require(len(payload) <= MAX_FRAME_BYTES, "helper response is oversized")
    control.sendall(struct.pack("!I", len(payload)) + payload)


def _send_frame_with_descriptor(
    control: socket.socket,
    value: dict[str, Any],
    descriptor: int,
) -> None:
    """Send one canonical frame and exactly one already-open directory FD."""
    payload = _canonical_bytes(value)
    _require(len(payload) <= MAX_FRAME_BYTES, "helper response is oversized")
    header = struct.pack("!I", len(payload))
    rights = array.array("i", [descriptor])
    sent = control.sendmsg(
        [header],
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
    )
    _require(0 < sent <= len(header), "project descriptor frame header was not sent")
    if sent < len(header):
        control.sendall(header[sent:])
    control.sendall(payload)


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


def _recv_frame(control: socket.socket, label: str) -> dict[str, Any]:
    header = _recv_exact(control, 4)
    size = struct.unpack("!I", header)[0]
    _require(0 < size <= MAX_FRAME_BYTES, f"{label} frame size differs")
    raw = _recv_exact(control, size)
    return _strict_frame(raw, label)


def _recv_request_and_descriptors(
    control: socket.socket,
) -> tuple[dict[str, Any], tuple[int, ...]]:
    integers = array.array("i")
    header, ancillary, flags, _address = control.recvmsg(
        4,
        socket.CMSG_SPACE(MAX_DESCRIPTOR_COUNT * integers.itemsize),
    )
    _require(
        not (flags & (getattr(socket, "MSG_TRUNC", 0) | getattr(socket, "MSG_CTRUNC", 0))),
        "request frame or descriptor rights were truncated",
    )
    received: list[int] = []
    try:
        _require(0 < len(header) <= 4, "request frame header differs")
        if len(header) < 4:
            header += _recv_exact(control, 4 - len(header))
        size = struct.unpack("!I", header)[0]
        for level, kind, data in ancillary:
            _require(
                level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS,
                "request contains foreign ancillary data",
            )
            usable = len(data) - (len(data) % integers.itemsize)
            integers.frombytes(data[:usable])
            received.extend(integers.tolist())
            integers = array.array("i")
        _require(
            1 <= len(received) <= MAX_DESCRIPTOR_COUNT
            and len(set(received)) == len(received),
            "request descriptor count differs",
        )
        _require(0 < size <= MAX_FRAME_BYTES, "request frame size differs")
        for descriptor in received:
            flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
            fcntl.fcntl(descriptor, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
        raw = _recv_exact(control, size)
        return _strict_frame(raw, "request"), tuple(received)
    except BaseException:
        for descriptor in received:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode),
    )


def _validate_request(
    request: dict[str, Any],
    descriptors: tuple[int, ...],
) -> tuple[str, tuple[str, ...], tuple[tuple[int, ...], ...]]:
    required = {
        "protocol",
        "operation_set",
        "project_basename",
        "scratch_label",
        "component_names",
        "component_identities",
        "descriptor_count",
        "receipt_payload_sha256",
        "authorization_scope_sha256",
        "workspace_binding_sha256",
        "descriptor_set_sha256",
    }
    _require(set(request) == required, "request fields differ")
    _require(request["protocol"] == PROTOCOL, "request protocol differs")
    _require(
        request["operation_set"]
        == [
            "create_project_directory_exclusive",
            "create_scratch_directory_exclusive",
        ],
        "request operation set differs",
    )
    project = request["project_basename"]
    _require(
        type(project) is str
        and 1 <= len(project) <= 64
        and project[0].isalnum()
        and all(character.isascii() and (character.isalnum() or character in "_-") for character in project),
        "request project basename differs",
    )
    _require(request["scratch_label"] == SCRATCH_LABEL, "request scratch label differs")
    names = request["component_names"]
    identities = request["component_identities"]
    count = request["descriptor_count"]
    _require(
        type(count) is int
        and type(count) is not bool
        and count == len(descriptors)
        and type(names) is list
        and len(names) + 1 == count
        and all(
            type(name) is str
            and name not in {"", ".", ".."}
            and "/" not in name
            and "\\" not in name
            for name in names
        ),
        "request descriptor topology differs",
    )
    _require(
        type(identities) is list
        and len(identities) == len(names)
        and all(
            type(identity) is list
            and len(identity) == 6
            and all(type(item) is int and type(item) is not bool for item in identity)
            for identity in identities
        ),
        "request component identities differ",
    )
    for field in (
        "receipt_payload_sha256",
        "authorization_scope_sha256",
        "workspace_binding_sha256",
        "descriptor_set_sha256",
    ):
        value = request[field]
        _require(
            type(value) is str
            and len(value) == 64
            and value != "0" * 64
            and all(character in "0123456789abcdef" for character in value),
            f"request {field} differs",
        )
    return project, tuple(names), tuple(tuple(identity) for identity in identities)


def _replay_descriptor_chain(
    descriptors: tuple[int, ...],
    names: tuple[str, ...],
    identities: tuple[tuple[int, ...], ...],
) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    _require(stat.S_ISDIR(os.fstat(descriptors[0]).st_mode), "root anchor is not a directory")
    for index, (name, expected) in enumerate(zip(names, identities, strict=True)):
        parent = descriptors[index]
        retained = descriptors[index + 1]
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        verification = os.open(name, flags, dir_fd=parent)
        try:
            opened = os.fstat(verification)
            retained_info = os.fstat(retained)
            after = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _require(
                stat.S_ISDIR(before.st_mode)
                and not stat.S_ISLNK(before.st_mode)
                and _directory_identity(before) == expected
                and _directory_identity(opened) == expected
                and _directory_identity(retained_info) == expected
                and _directory_identity(after) == expected,
                "root component identity drifted",
            )
        finally:
            os.close(verification)


def _expect_command(control: socket.socket, command: str) -> None:
    value = _recv_frame(control, command)
    _require(
        value == {"protocol": PROTOCOL, "command": command},
        f"{command} command differs",
    )


def _expect_scratch_command(control: socket.socket) -> bool:
    value = _recv_frame(control, "continue_scratch")
    _require(
        type(value) is dict
        and set(value) == {"protocol", "command"}
        and value["protocol"] == PROTOCOL
        and value["command"] in {"continue_scratch", SESSION_HANDOFF_COMMAND},
        "continue_scratch command differs",
    )
    return value["command"] == SESSION_HANDOFF_COMMAND


def _unrelated_fd_count(control_fd: int) -> int:
    count = 0
    for descriptor in range(3, 256):
        if descriptor == control_fd:
            continue
        try:
            fcntl.fcntl(descriptor, fcntl.F_GETFD)
        except OSError:
            continue
        count += 1
    return count


def _run_child(control_fd: int) -> int:
    control = socket.socket(fileno=control_fd)
    control.settimeout(FIXED_SOCKET_TIMEOUT_SECONDS)
    descriptors: tuple[int, ...] = ()
    project_fd = -1
    scratch_fd = -1
    effect_started = False
    try:
        os.umask(0o077)
        flags = fcntl.fcntl(control_fd, fcntl.F_GETFD)
        fcntl.fcntl(control_fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
        ready = dict(READY)
        ready["unrelated_fd_count"] = _unrelated_fd_count(control_fd)
        _send_frame(control, ready)
        request, descriptors = _recv_request_and_descriptors(control)
        project, names, identities = _validate_request(request, descriptors)
        _replay_descriptor_chain(descriptors, names, identities)
        _send_frame(control, VALIDATED)
        _expect_command(control, "begin_project")
        effect_started = True
        os.mkdir(project, mode=0o700, dir_fd=descriptors[-1])
        directory_flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        project_before = os.stat(
            project,
            dir_fd=descriptors[-1],
            follow_symlinks=False,
        )
        project_fd = os.open(project, directory_flags, dir_fd=descriptors[-1])
        project_opened = os.fstat(project_fd)
        project_after = os.stat(
            project,
            dir_fd=descriptors[-1],
            follow_symlinks=False,
        )
        _require(
            stat.S_ISDIR(project_opened.st_mode)
            and _directory_identity(project_before)
            == _directory_identity(project_opened)
            == _directory_identity(project_after)
            and stat.S_IMODE(project_opened.st_mode) == 0o700,
            "created project identity or mode differs",
        )
        _send_frame(control, PROJECT_CREATED)
        handoff_project_fd = _expect_scratch_command(control)
        os.mkdir(SCRATCH_LABEL, mode=0o700, dir_fd=project_fd)
        scratch_before = os.stat(
            SCRATCH_LABEL,
            dir_fd=project_fd,
            follow_symlinks=False,
        )
        scratch_fd = os.open(SCRATCH_LABEL, directory_flags, dir_fd=project_fd)
        scratch_opened = os.fstat(scratch_fd)
        scratch_after = os.stat(
            SCRATCH_LABEL,
            dir_fd=project_fd,
            follow_symlinks=False,
        )
        _require(
            stat.S_ISDIR(scratch_opened.st_mode)
            and _directory_identity(scratch_before)
            == _directory_identity(scratch_opened)
            == _directory_identity(scratch_after)
            and stat.S_IMODE(scratch_opened.st_mode) == 0o700,
            "created scratch identity or mode differs",
        )
        if handoff_project_fd:
            _send_frame_with_descriptor(
                control,
                {
                    "protocol": PROTOCOL,
                    "state": SESSION_COMPLETED_STATE,
                    "operations_completed": list(COMPLETED["operations_completed"]),
                    "request_sha256": hashlib.sha256(_canonical_bytes(request)).hexdigest(),
                    "project_identity": list(_directory_identity(project_opened)),
                },
                project_fd,
            )
        else:
            _send_frame(control, COMPLETED)
        return 0
    except BaseException as exc:
        try:
            _send_frame(
                control,
                {
                    "protocol": PROTOCOL,
                    "state": "outcome_uncertain" if effect_started else "rejected_no_effect",
                    "error": type(exc).__name__,
                },
            )
        except BaseException:
            pass
        return 3 if effect_started else 2
    finally:
        for descriptor in (scratch_fd, project_fd, *reversed(descriptors)):
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
        or len(values) != 3
        or values[0] != CHILD_FLAG
        or not values[1].isascii()
        or not values[1].isdigit()
        or not values[2].isascii()
        or not values[2].isdigit()
    ):
        return 64
    descriptor = int(values[1], 10)
    source_descriptor = int(values[2], 10)
    if descriptor < 3 or source_descriptor < 3 or descriptor == source_descriptor:
        return 64
    try:
        os.close(source_descriptor)
    except OSError:
        return 64
    return _run_child(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
