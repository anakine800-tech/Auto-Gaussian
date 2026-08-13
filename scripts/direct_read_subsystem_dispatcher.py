#!/usr/bin/env python3
"""Fixed clean-exec closed-union dispatcher for direct read operations."""

from __future__ import annotations

if globals().get("_AUTO_G16_DIRECT_READ_DISPATCHER_EXECUTED", False):
    raise ImportError("direct read dispatcher module already executed")
_AUTO_G16_DIRECT_READ_DISPATCHER_EXECUTED = True

import hashlib
import json
import os
import struct
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, NamedTuple

import direct_shared_fixed_ssh_channel as CHANNEL


MODULE_NAME = "direct_read_subsystem_dispatcher"
MAX_REQUEST_BYTES = CHANNEL.MAX_CONTROL_FRAME_BYTES
ALLOWED_OPERATIONS = frozenset({
    "acquire_exact_qstat",
    "fetch_terminal_minimum_bundle",
})
class _BudgetRecord(NamedTuple):
    capability: object
    pid: int
    epoch: object
    seal: object
    started_at: float
    outer_deadline: float
    frame_sha256: str | None
    operation: str | None
    effective_deadline: float | None

class DirectReadSubsystemDispatcherError(ValueError):
    """The fixed read request could not be dispatched exactly."""


class _ReadDispatchBudget:
    __slots__ = ("_key", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("read dispatch budgets are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("read dispatch budgets are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("read dispatch budgets are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("read dispatch budgets are not serializable")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectReadSubsystemDispatcherError(message)


def _source_sha(module: types.ModuleType) -> str:
    path = Path(module.__file__).resolve(strict=True)
    _require(path.parent == Path(__file__).resolve().parent, "dispatcher module origin differs")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        hasher = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
         before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns),
        "dispatcher source identity drifted",
    )
    return hasher.hexdigest()


def _build_dispatch_budget_owner() -> tuple[object, ...]:
    registry: dict[int, _BudgetRecord] = {}
    lock = threading.RLock()
    epoch = object()

    def exact(budget: object) -> _BudgetRecord:
        with lock:
            record = (
                registry.get(getattr(budget, "_key", -1))
                if type(budget) is _ReadDispatchBudget else None
            )
        _require(
            type(record) is _BudgetRecord
            and record.capability is budget
            and record.pid == os.getpid()
            and record.epoch is epoch
            and record.seal is budget._seal,
            "dispatch budget is absent, forged, forked, or terminal",
        )
        return record

    def issue() -> tuple[_ReadDispatchBudget, float]:
        started_at = time.monotonic()
        outer_deadline = started_at + CHANNEL.SUBMIT_OPERATION_TIMEOUT_SECONDS
        budget = object.__new__(_ReadDispatchBudget)
        budget._key = id(budget)
        budget._seal = object()
        record = _BudgetRecord(
            budget, os.getpid(), epoch, budget._seal,
            started_at, outer_deadline, None, None, None,
        )
        with lock:
            _require(budget._key not in registry, "dispatch budget key collision")
            registry[budget._key] = record
        return budget, outer_deadline

    def bind(budget: _ReadDispatchBudget, frame: bytes, operation: str) -> None:
        record = exact(budget)
        _require(
            type(frame) is bytes
            and operation in ALLOWED_OPERATIONS
            and record.frame_sha256 is None
            and record.operation is None
            and record.effective_deadline is None,
            "dispatch budget binding differs",
        )
        with lock:
            _require(registry.get(budget._key) is record, "dispatch budget bind raced")
            registry[budget._key] = record._replace(
                frame_sha256=hashlib.sha256(frame).hexdigest(),
                operation=operation,
            )

    def consume(
        budget: object,
        frame: bytes,
        operation: str,
        reviewed_timeout_seconds: int,
    ) -> _ReadDispatchBudget:
        _assert_dispatcher_binding()
        record = exact(budget)
        try:
            _require(
                type(frame) is bytes
                and record.frame_sha256 == hashlib.sha256(frame).hexdigest()
                and record.operation == operation
                and record.effective_deadline is None
                and operation in ALLOWED_OPERATIONS
                and type(reviewed_timeout_seconds) is int
                and 0 < reviewed_timeout_seconds <= 3600,
                "dispatch budget successor binding differs",
            )
            effective = min(
                record.outer_deadline,
                record.started_at + float(reviewed_timeout_seconds),
            )
            _require(time.monotonic() < effective, "read dispatch budget expired")
        except BaseException:
            with lock:
                if registry.get(budget._key) is record:
                    del registry[budget._key]
            raise
        with lock:
            _require(registry.get(budget._key) is record, "dispatch budget consume raced")
            registry[budget._key] = record._replace(
                effective_deadline=effective,
            )
        return budget

    def deadline(budget: object) -> float:
        _assert_dispatcher_binding()
        record = exact(budget)
        _require(
            type(record.frame_sha256) is str
            and record.operation in ALLOWED_OPERATIONS
            and type(record.effective_deadline) is float,
            "dispatch budget is unconsumed",
        )
        return record.effective_deadline

    def retire(budget: object) -> None:
        _assert_dispatcher_binding()
        record = exact(budget)
        _require(
            type(record.effective_deadline) is float,
            "only a live dispatch budget can retire",
        )
        with lock:
            _require(registry.get(budget._key) is record, "dispatch budget retire raced")
            del registry[budget._key]

    def abandon(budget: object) -> None:
        with lock:
            record = (
                registry.get(getattr(budget, "_key", -1))
                if type(budget) is _ReadDispatchBudget else None
            )
            if type(record) is _BudgetRecord and record.capability is budget:
                del registry[budget._key]

    def after_fork() -> None:
        nonlocal lock, epoch
        registry.clear()
        lock = threading.RLock()
        epoch = object()

    return issue, bind, consume, deadline, retire, abandon, after_fork


(
    _issue_dispatch_budget,
    _bind_dispatch_budget_once,
    _consume_dispatch_budget_once,
    _dispatch_deadline_value,
    _retire_dispatch_budget_once,
    _abandon_dispatch_budget,
    _BUDGET_AFTER_FORK,
) = _build_dispatch_budget_owner()


def _read_request_frame_once(deadline: float) -> bytes:
    _require(type(deadline) is float, "dispatcher deadline differs")
    header = CHANNEL._read_exact_until(
        0, 4, deadline, "read subsystem request header",
    )
    size = struct.unpack("!I", header)[0]
    _require(0 < size <= MAX_REQUEST_BYTES, "read subsystem request size differs")
    payload = CHANNEL._read_exact_until(
        0, size, deadline, "read subsystem request",
    )
    CHANNEL._require_eof_until(0, deadline, "read subsystem request")
    frame = header + payload
    CHANNEL._validate_single_canonical_frame_bytes(frame)
    return frame


def _peek_closed_operation_tag(frame: bytes) -> str:
    CHANNEL._validate_single_canonical_frame_bytes(frame)
    try:
        value = json.loads(frame[4:].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectReadSubsystemDispatcherError(
            "read subsystem request is malformed"
        ) from exc
    operation = value.get("operation") if type(value) is dict else None
    _require(
        type(operation) is str and operation in ALLOWED_OPERATIONS,
        "read subsystem operation is unsupported",
    )
    return operation


def _canonical_successor(module_name: str, filename: str) -> types.ModuleType:
    module = __import__(module_name)
    expected = (Path(__file__).resolve().parent / filename).resolve(strict=True)
    _require(
        type(module) is types.ModuleType
        and Path(module.__file__).resolve(strict=True) == expected,
        "read subsystem successor origin differs",
    )
    _source_sha(module)
    return module


def _dispatch_request_frame_once(
    frame: bytes,
    response_descriptor: int,
    budget: _ReadDispatchBudget,
) -> None:
    _assert_dispatcher_binding()
    _require(
        type(response_descriptor) is int and response_descriptor >= 0
        and type(budget) is _ReadDispatchBudget,
        "read subsystem dispatch arguments differ",
    )
    operation = _peek_closed_operation_tag(frame)
    if operation == "acquire_exact_qstat":
        qstat = _canonical_successor(
            "direct_qstat_acquisition", "direct_qstat_acquisition.py",
        )
        qstat._assert_module_binding()
        response = (
            qstat.DirectQstatServerOwner.production()
            ._handle_dispatched_once(frame, budget)
        )
        CHANNEL._write_frame_until(
            response_descriptor, response, _dispatch_deadline_value(budget),
        )
        return
    fetch = _canonical_successor(
        "direct_fetch_acquisition", "direct_fetch_acquisition.py",
    )
    fetch._assert_module_binding()
    fetch.serve_dispatched_fetch_request_once(
        frame, response_descriptor, budget,
    )


def _server_subsystem_main() -> int:
    _assert_dispatcher_binding()
    _require(
        sys.flags.isolated == 1
        and sys.flags.no_site == 1
        and Path.cwd() == Path("/")
        and os.environ.get("LANG") == "C"
        and os.environ.get("LC_ALL") == "C",
        "direct read subsystem requires fixed -I -S clean exec",
    )
    CHANNEL._assert_production_binding()
    budget, outer_deadline = _issue_dispatch_budget()
    try:
        frame = _read_request_frame_once(outer_deadline)
        operation = _peek_closed_operation_tag(frame)
        _bind_dispatch_budget_once(budget, frame, operation)
        _dispatch_request_frame_once(frame, 1, budget)
        _retire_dispatch_budget_once(budget)
        budget = None
    finally:
        if budget is not None:
            _abandon_dispatch_budget(budget)
    return 0


def _after_fork_child() -> None:
    _BUDGET_AFTER_FORK()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    _require(
        arguments == ["--fixed-read-subsystem"],
        "direct read subsystem argv differs",
    )
    return _server_subsystem_main()


_FROZEN_MODULE = sys.modules[__name__]
_EXECUTED_SOURCE_SHA256 = _source_sha(_FROZEN_MODULE)
_FROZEN_ENTRIES = (
    _issue_dispatch_budget,
    _bind_dispatch_budget_once,
    _consume_dispatch_budget_once,
    _dispatch_deadline_value,
    _retire_dispatch_budget_once,
    _abandon_dispatch_budget,
    _BUDGET_AFTER_FORK,
    _read_request_frame_once,
    _peek_closed_operation_tag,
    _canonical_successor,
    _dispatch_request_frame_once,
    _server_subsystem_main,
    _after_fork_child,
    main,
)
_FROZEN_CHANNEL = CHANNEL
_FROZEN_CHANNEL_SOURCE_SHA256 = _source_sha(CHANNEL)


def _assert_dispatcher_binding() -> None:
    module = sys.modules.get(__name__)
    _require(
        type(module) is types.ModuleType
        and module is _FROZEN_MODULE
        and _source_sha(module) == _EXECUTED_SOURCE_SHA256
        and CHANNEL is _FROZEN_CHANNEL
        and _source_sha(CHANNEL) == _FROZEN_CHANNEL_SOURCE_SHA256
        and _FROZEN_ENTRIES == (
            _issue_dispatch_budget,
            _bind_dispatch_budget_once,
            _consume_dispatch_budget_once,
            _dispatch_deadline_value,
            _retire_dispatch_budget_once,
            _abandon_dispatch_budget,
            _BUDGET_AFTER_FORK,
            _read_request_frame_once,
            _peek_closed_operation_tag,
            _canonical_successor,
            _dispatch_request_frame_once,
            _server_subsystem_main,
            _after_fork_child,
            main,
        ),
        "read subsystem dispatcher source or entry binding differs",
    )
    CHANNEL._assert_production_binding()


__all__ = [
    "DirectReadSubsystemDispatcherError",
]


if __name__ == "__main__":  # pragma: no cover - fixed server subsystem only
    raise SystemExit(main())
