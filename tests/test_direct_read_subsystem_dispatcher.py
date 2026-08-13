#!/usr/bin/env python3
"""Offline hostile tests for the fixed direct read closed-union dispatcher."""

from __future__ import annotations

import json
import copy
import inspect
import os
import pathlib
import pickle
import struct
import sys
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import direct_read_subsystem_dispatcher as DISPATCH  # noqa: E402
import direct_shared_fixed_ssh_channel as CHANNEL  # noqa: E402


class DirectReadSubsystemDispatcherTests(unittest.TestCase):
    def frame(self, operation: object) -> bytes:
        return CHANNEL._canonical_frame({
            "protocol": CHANNEL.READ_PROTOCOL,
            "operation": operation,
        })

    def test_closed_union_accepts_only_exact_two_tags(self) -> None:
        self.assertEqual(
            DISPATCH._peek_closed_operation_tag(
                self.frame("acquire_exact_qstat")
            ),
            "acquire_exact_qstat",
        )
        self.assertEqual(
            DISPATCH._peek_closed_operation_tag(
                self.frame("fetch_terminal_minimum_bundle")
            ),
            "fetch_terminal_minimum_bundle",
        )
        for value in (
            "", "Acquire_Exact_Qstat", "fetch", "cancel", "qdel", None, 1,
        ):
            with self.subTest(value=value):
                with self.assertRaises(
                    DISPATCH.DirectReadSubsystemDispatcherError
                ):
                    DISPATCH._peek_closed_operation_tag(self.frame(value))

    def test_malformed_truncated_extra_and_noncanonical_fail_before_tag(self) -> None:
        valid = self.frame("acquire_exact_qstat")
        hostile = (
            b"",
            struct.pack("!I", 0),
            valid[:-1],
            valid + b"x",
            struct.pack("!I", 1) + b"\xff",
            struct.pack("!I", len(b'{"operation": "acquire_exact_qstat"}'))
            + b'{"operation": "acquire_exact_qstat"}',
        )
        for raw in hostile:
            with self.subTest(raw=raw[:20]):
                with self.assertRaises((
                    CHANNEL.SharedFixedSSHChannelError,
                    DISPATCH.DirectReadSubsystemDispatcherError,
                )):
                    DISPATCH._peek_closed_operation_tag(raw)

    def test_main_has_fixed_single_argv_only(self) -> None:
        for argv in ([], ["--other"], ["--fixed-read-subsystem", "x"]):
            with self.subTest(argv=argv):
                with self.assertRaises(
                    DISPATCH.DirectReadSubsystemDispatcherError
                ):
                    DISPATCH.main(argv)

    def test_dispatcher_entry_rebind_fails_before_successor(self) -> None:
        original = DISPATCH._peek_closed_operation_tag
        DISPATCH._peek_closed_operation_tag = lambda _frame: "acquire_exact_qstat"
        try:
            with self.assertRaises(
                DISPATCH.DirectReadSubsystemDispatcherError
            ):
                DISPATCH._assert_dispatcher_binding()
        finally:
            DISPATCH._peek_closed_operation_tag = original
        DISPATCH._assert_dispatcher_binding()

    def test_private_budget_starts_before_parse_only_shortens_and_is_single_use(self) -> None:
        self.assertFalse(hasattr(DISPATCH, "_BUDGET_REGISTRY"))
        self.assertFalse(hasattr(DISPATCH, "_BUDGET_LOCK"))
        frame = self.frame("fetch_terminal_minimum_bundle")
        started = time.monotonic()
        budget, outer = DISPATCH._issue_dispatch_budget()
        DISPATCH._bind_dispatch_budget_once(
            budget, frame, "fetch_terminal_minimum_bundle",
        )
        consumed = DISPATCH._consume_dispatch_budget_once(
            budget, frame, "fetch_terminal_minimum_bundle", 30,
        )
        self.assertAlmostEqual(
            outer, started + CHANNEL.SUBMIT_OPERATION_TIMEOUT_SECONDS,
            delta=0.1,
        )
        self.assertIs(consumed, budget)
        effective = DISPATCH._dispatch_deadline_value(budget)
        self.assertAlmostEqual(effective, started + 30.0, delta=0.1)
        source = inspect.getsource(DISPATCH._consume_dispatch_budget_once)
        self.assertIn("record.started_at + float(reviewed_timeout_seconds)", source)
        self.assertNotIn("time.monotonic() +", source)
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaises(TypeError):
                operation(budget)
        DISPATCH._retire_dispatch_budget_once(budget)
        with self.assertRaises(DISPATCH.DirectReadSubsystemDispatcherError):
            DISPATCH._consume_dispatch_budget_once(
                budget, frame, "fetch_terminal_minimum_bundle", 30,
            )
        with self.assertRaises(DISPATCH.DirectReadSubsystemDispatcherError):
            DISPATCH._dispatch_deadline_value(budget)

    @unittest.skipUnless(hasattr(os, "fork"), "fork revocation needs POSIX")
    def test_budget_frame_operation_splice_and_fork_are_terminal(self) -> None:
        frame = self.frame("acquire_exact_qstat")
        budget, _outer = DISPATCH._issue_dispatch_budget()
        DISPATCH._bind_dispatch_budget_once(
            budget, frame, "acquire_exact_qstat",
        )
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child assertion
            os.close(read_fd)
            try:
                DISPATCH._consume_dispatch_budget_once(
                    budget, frame, "acquire_exact_qstat", 30,
                )
            except BaseException:
                os.write(write_fd, b"REVOKED")
            else:
                os.write(write_fd, b"CURRENT")
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        self.assertEqual(os.read(read_fd, 16), b"REVOKED")
        os.close(read_fd)
        os.waitpid(pid, 0)
        with self.assertRaises(DISPATCH.DirectReadSubsystemDispatcherError):
            DISPATCH._consume_dispatch_budget_once(
                budget,
                self.frame("fetch_terminal_minimum_bundle"),
                "acquire_exact_qstat",
                30,
            )
        DISPATCH._abandon_dispatch_budget(budget)
        with self.assertRaises(DISPATCH.DirectReadSubsystemDispatcherError):
            DISPATCH._consume_dispatch_budget_once(
                budget, frame, "acquire_exact_qstat", 30,
            )


if __name__ == "__main__":
    unittest.main()
