#!/usr/bin/env python3
"""Offline hostile tests for the direct local fetch materializer."""

from __future__ import annotations

import copy
import errno
import importlib
import inspect
import json
import os
import pathlib
import pickle
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import direct_local_fetch_materializer as MATERIALIZER  # noqa: E402


class DirectLocalFetchMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.target_root = pathlib.Path(self.temporary.name).resolve()
        self.payloads = (
            b"%chk=approved-input.chk\n# opt freq\n",
            b"#!/bin/sh\n# synthetic only\n",
            b"1" * 64 + b"  approved-input.gjf\n",
            b'{"schema":"synthetic-submission-receipt/1"}\n',
            b" Synthetic Gaussian log bytes only.\n",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def policy(self, root: pathlib.Path | None = None) -> dict[str, object]:
        return MATERIALIZER._build_reviewed_target_policy_for_tests(
            target_root=str((root or self.target_root).resolve()),
            review_id="local-fetch-target-review-" + "1" * 64,
        )

    def target(self, root: pathlib.Path | None = None):
        owner = MATERIALIZER._issue_offline_target_owner_for_tests(
            target_root=str((root or self.target_root).resolve()),
            review_id="local-fetch-target-review-" + "1" * 64,
        )
        capability = owner.issue_target_once(
            project="project_a",
            attempt_id="qsub-attempt-" + "2" * 64,
            job_id="123.master",
            w5_receipt_sha256="3" * 64,
            read_profile_sha256="4" * 64,
        )
        return owner, capability

    def prepared(self):
        owner, capability = self.target()
        lease = MATERIALIZER.issue_offline_synthetic_stream_lease_once(
            capability, self.payloads
        )
        return owner, capability, lease

    def leaf(self, capability) -> pathlib.Path:
        return self.target_root / MATERIALIZER._target_record(capability).leaf_basename

    def test_exact_five_files_are_private_fsynced_and_manifest_is_last_evidence(self) -> None:
        _owner, capability, lease = self.prepared()
        projection = lease.portable_projection()
        self.assertFalse(projection["authorizes_effect"])
        self.assertFalse(projection["production_integration"])
        self.assertEqual(projection["required_production_successor"], MATERIALIZER.PRODUCTION_SUCCESSOR)
        manifest = MATERIALIZER.materialize_direct_fetch_once(capability, lease)
        leaf = self.target_root / manifest["target"]["leaf_basename"]
        self.assertEqual(stat.S_IMODE(leaf.stat().st_mode), 0o700)
        self.assertEqual(
            {item.name for item in leaf.iterdir()},
            set(MATERIALIZER.ARTIFACT_BASENAMES) | {MATERIALIZER.MANIFEST_BASENAME},
        )
        for basename, payload in zip(MATERIALIZER.ARTIFACT_BASENAMES, self.payloads, strict=True):
            path = leaf / basename
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)
        raw_manifest = (leaf / MATERIALIZER.MANIFEST_BASENAME).read_bytes()
        self.assertEqual(raw_manifest, MATERIALIZER.canonical_bytes(manifest))
        self.assertEqual(MATERIALIZER.validate_manifest(json.loads(raw_manifest)), manifest)
        self.assertFalse(manifest["authority"]["authorizes_effect"])
        self.assertFalse(manifest["authority"]["scientific_acceptance"])
        self.assertFalse(manifest["integration"]["production_integration"])
        self.assertTrue(manifest["safety"]["bytes_safely_materialized"])

    def test_public_materializer_has_no_path_root_iterator_callback_or_dict_seam(self) -> None:
        signature = inspect.signature(MATERIALIZER.materialize_direct_fetch_once)
        self.assertEqual(tuple(signature.parameters), ("target_capability", "stream_lease"))
        fake_values = (
            ({}, {}),
            (self.target_root, iter(self.payloads)),
            (object(), lambda: self.payloads),
        )
        for target, stream in fake_values:
            with self.subTest(target=type(target).__name__, stream=type(stream).__name__):
                with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "exact"):
                    MATERIALIZER.materialize_direct_fetch_once(target, stream)

    def test_policy_is_hash_bound_repo_external_and_has_no_issue_override(self) -> None:
        policy = self.policy()
        self.assertEqual(MATERIALIZER.validate_target_policy(policy), policy)
        self.assertFalse(hasattr(MATERIALIZER, "build_reviewed_target_policy"))
        self.assertFalse(
            hasattr(MATERIALIZER.LocalFetchTargetOwner, "from_reviewed_policy_bytes")
        )
        self.assertFalse(policy["policy"]["caller_path_override_allowed"])
        self.assertFalse(policy["policy"]["caller_root_override_allowed"])
        self.assertFalse(policy["authority"]["authorizes_effect"])
        self.assertFalse(policy["authority"]["production_integration"])
        self.assertFalse(policy["authority"]["caller_bytes_can_issue_owner"])
        signature = inspect.signature(MATERIALIZER.LocalFetchTargetOwner.issue_target_once)
        self.assertNotIn("path", signature.parameters)
        self.assertNotIn("root", signature.parameters)
        arbitrary_bytes = MATERIALIZER.canonical_bytes(policy)
        with self.assertRaisesRegex(TypeError, "module-issued only"):
            MATERIALIZER.LocalFetchTargetOwner(arbitrary_bytes)
        with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "exact"):
            MATERIALIZER.materialize_direct_fetch_once(policy, arbitrary_bytes)
        repository_policy = MATERIALIZER._build_reviewed_target_policy_for_tests(
            target_root=str(ROOT.resolve()),
            review_id="local-fetch-target-review-" + "5" * 64,
        )
        with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "repo-external"):
            MATERIALIZER._issue_offline_target_owner_for_tests(
                target_root=str(ROOT.resolve()),
                review_id="local-fetch-target-review-" + "5" * 64,
            )
        changed = copy.deepcopy(policy)
        changed["target_root"] = str(self.target_root.parent)
        with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "hash"):
            MATERIALIZER.validate_target_policy(changed)

    def test_ancestor_symlink_and_noncanonical_root_reject_before_capability(self) -> None:
        with tempfile.TemporaryDirectory() as outer:
            outer_path = pathlib.Path(outer).resolve()
            real = outer_path / "real"
            real.mkdir(mode=0o700)
            link = outer_path / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "canonical"):
                MATERIALIZER._build_reviewed_target_policy_for_tests(
                    target_root=str(link),
                    review_id="local-fetch-target-review-" + "6" * 64,
                )

    def test_capability_and_lease_are_nonconstructible_noncopyable_and_nonserializable(self) -> None:
        owner, capability, lease = self.prepared()
        values = (owner, capability, lease)
        for value in values:
            with self.subTest(value=type(value).__name__, operation="copy"):
                with self.assertRaises(TypeError):
                    copy.copy(value)
            with self.subTest(value=type(value).__name__, operation="deepcopy"):
                with self.assertRaises(TypeError):
                    copy.deepcopy(value)
            with self.subTest(value=type(value).__name__, operation="pickle"):
                with self.assertRaises(TypeError):
                    pickle.dumps(value)
        with self.assertRaises(TypeError):
            MATERIALIZER.LocalFetchTargetCapability()
        with self.assertRaises(TypeError):
            MATERIALIZER.DirectFetchStreamLease()
        with self.assertRaises(TypeError):
            MATERIALIZER.LocalFetchTargetOwner()

    def test_existing_leaf_directory_file_and_symlink_are_zero_effect(self) -> None:
        cases = ("directory", "file", "symlink")
        for kind in cases:
            with self.subTest(kind=kind):
                target = self.target_root / kind
                target.mkdir(mode=0o700)
                _owner, capability = self.target(target)
                lease = MATERIALIZER.issue_offline_synthetic_stream_lease_once(capability, self.payloads)
                leaf = target / MATERIALIZER._target_record(capability).leaf_basename
                if kind == "directory":
                    leaf.mkdir()
                elif kind == "file":
                    leaf.write_bytes(b"existing")
                else:
                    leaf.symlink_to(target, target_is_directory=True)
                with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "exclusive target leaf"):
                    MATERIALIZER.materialize_direct_fetch_once(capability, lease)
                self.assertFalse((leaf / MATERIALIZER.MANIFEST_BASENAME).exists() if leaf.is_dir() else False)

    def test_leaf_symlink_and_mkdir_open_swap_reject_without_following(self) -> None:
        _owner, capability, lease = self.prepared()
        leaf = self.leaf(capability)
        leaf.symlink_to(self.target_root, target_is_directory=True)
        with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
            MATERIALIZER.materialize_direct_fetch_once(capability, lease)
        leaf.unlink()

        _owner, capability, lease = self.prepared()
        leaf = self.leaf(capability)
        original_open = MATERIALIZER.os.open
        swapped = False

        def racing_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == leaf.name and flags & os.O_DIRECTORY and not swapped:
                swapped = True
                leaf.rmdir()
                leaf.symlink_to(self.target_root, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)

        with mock.patch.object(MATERIALIZER.os, "open", side_effect=racing_open):
            with self.assertRaises((MATERIALIZER.DirectLocalFetchMaterializerError, OSError)):
                MATERIALIZER.materialize_direct_fetch_once(capability, lease)
        self.assertTrue(swapped)
        self.assertFalse((self.target_root / MATERIALIZER.MANIFEST_BASENAME).exists())

    def test_target_fd_close_reuse_and_identity_drift_fail_closed(self) -> None:
        _owner, capability = self.target()
        record = MATERIALIZER._target_record(capability)
        stale_fd = record.root_identity.descriptor
        os.close(stale_fd)
        replacement = os.open(str(ROOT), os.O_RDONLY | os.O_DIRECTORY)
        try:
            if replacement != stale_fd:
                os.dup2(replacement, stale_fd)
            with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "identity drifted"):
                capability.assert_current()
        finally:
            for descriptor in {replacement, stale_fd}:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def test_fixed_order_extra_missing_size_hash_and_oversized_records_fail_closed(self) -> None:
        mutations = []
        base = tuple(
            MATERIALIZER._synthetic_record_for_tests(name, raw)
            for name, raw in zip(MATERIALIZER.ARTIFACT_BASENAMES, self.payloads, strict=True)
        )
        mutations.append(("order", (base[1], base[0], *base[2:])))
        mutations.append(("extra", (*base, MATERIALIZER._synthetic_record_for_tests("extra.out", b"x"))))
        mutations.append(("missing", base[:-1]))
        wrong_size = list(base)
        wrong_size[0] = MATERIALIZER._synthetic_record_for_tests(base[0].basename, self.payloads[0], declared_size_bytes=str(len(self.payloads[0]) + 1))
        mutations.append(("size", tuple(wrong_size)))
        wrong_hash = list(base)
        wrong_hash[0] = MATERIALIZER._synthetic_record_for_tests(base[0].basename, self.payloads[0], declared_sha256="9" * 64)
        mutations.append(("hash", tuple(wrong_hash)))
        oversized = list(base)
        oversized[0] = MATERIALIZER._synthetic_record_for_tests(base[0].basename, b"", declared_size_bytes=str(MATERIALIZER.ARTIFACT_CAPS[base[0].basename] + 1), declared_sha256=MATERIALIZER.EMPTY_SHA)
        mutations.append(("oversized", tuple(oversized)))
        for label, records in mutations:
            with self.subTest(label=label):
                target = self.target_root / label
                target.mkdir(mode=0o700)
                _owner, capability = self.target(target)
                lease = MATERIALIZER._issue_synthetic_stream_records_for_tests_once(capability, records)
                with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
                    MATERIALIZER.materialize_direct_fetch_once(capability, lease)
                leaf = target / MATERIALIZER._target_record(capability).leaf_basename
                self.assertFalse((leaf / MATERIALIZER.MANIFEST_BASENAME).exists())

    def test_disconnect_and_oversized_chunk_leave_partial_without_manifest(self) -> None:
        for label, first in (
            ("disconnect", MATERIALIZER._synthetic_record_for_tests(
                MATERIALIZER.ARTIFACT_BASENAMES[0], self.payloads[0], disconnect_after_chunks=1
            )),
            ("chunk", MATERIALIZER._synthetic_record_for_tests(
                MATERIALIZER.ARTIFACT_BASENAMES[0], b"x" * (MATERIALIZER.CHUNK_SIZE_BYTES + 1),
                chunks=(b"x" * (MATERIALIZER.CHUNK_SIZE_BYTES + 1),)
            )),
        ):
            with self.subTest(label=label):
                target = self.target_root / label
                target.mkdir(mode=0o700)
                _owner, capability = self.target(target)
                rest = tuple(
                    MATERIALIZER._synthetic_record_for_tests(name, raw)
                    for name, raw in zip(MATERIALIZER.ARTIFACT_BASENAMES[1:], self.payloads[1:], strict=True)
                )
                lease = MATERIALIZER._issue_synthetic_stream_records_for_tests_once(capability, (first, *rest))
                with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
                    MATERIALIZER.materialize_direct_fetch_once(capability, lease)
                leaf = target / MATERIALIZER._target_record(capability).leaf_basename
                self.assertTrue((leaf / MATERIALIZER.ARTIFACT_BASENAMES[0]).exists())
                self.assertFalse((leaf / MATERIALIZER.MANIFEST_BASENAME).exists())

    def test_actual_stream_cap_is_checked_before_writing_excess_chunk(self) -> None:
        basename = "checksums.sha256"
        cap = MATERIALIZER.ARTIFACT_CAPS[basename]
        prefix = b"p" * (cap - 1)
        declared = b"p" * cap
        cases = (
            ("single-legal-max-chunk", (b"x" * MATERIALIZER.CHUNK_SIZE_BYTES,), b""),
            ("cap-with-prefix", (prefix, b"zz"), prefix),
        )
        for label, chunks, expected_partial in cases:
            with self.subTest(label=label):
                records = tuple(
                    MATERIALIZER._synthetic_record_for_tests(name, raw)
                    for name, raw in zip(
                        MATERIALIZER.ARTIFACT_BASENAMES,
                        self.payloads,
                        strict=True,
                    )
                )
                changed = list(records)
                changed[2] = MATERIALIZER._synthetic_record_for_tests(
                    basename,
                    declared,
                    chunks=chunks,
                )
                target = self.target_root / label
                target.mkdir(mode=0o700)
                _owner, capability = self.target(target)
                lease = MATERIALIZER._issue_synthetic_stream_records_for_tests_once(
                    capability,
                    tuple(changed),
                )

                with self.assertRaisesRegex(
                    MATERIALIZER.DirectLocalFetchMaterializerError,
                    "exceeded its fixed cap",
                ):
                    MATERIALIZER.materialize_direct_fetch_once(capability, lease)

                leaf = target / MATERIALIZER._target_record(capability).leaf_basename
                partial = leaf / basename
                self.assertEqual(partial.stat().st_size, len(expected_partial))
                self.assertLessEqual(partial.stat().st_size, cap)
                self.assertEqual(partial.read_bytes(), expected_partial)
                self.assertFalse((leaf / MATERIALIZER.ARTIFACT_BASENAMES[3]).exists())
                self.assertFalse((leaf / MATERIALIZER.MANIFEST_BASENAME).exists())

    def test_short_write_is_completed_and_enospc_retains_partial(self) -> None:
        _owner, capability, lease = self.prepared()
        original_write = MATERIALIZER.os.write

        def short_write(descriptor, data):
            return original_write(descriptor, data[: max(1, len(data) // 3)])

        with mock.patch.object(MATERIALIZER.os, "write", side_effect=short_write):
            manifest = MATERIALIZER.materialize_direct_fetch_once(capability, lease)
        self.assertEqual(MATERIALIZER.validate_manifest(manifest), manifest)

        target = self.target_root / "enospc"
        target.mkdir(mode=0o700)
        _owner, capability = self.target(target)
        records = tuple(
            MATERIALIZER._synthetic_record_for_tests(name, raw)
            for name, raw in zip(MATERIALIZER.ARTIFACT_BASENAMES, self.payloads, strict=True)
        )
        lease = MATERIALIZER._issue_synthetic_stream_records_for_tests_once(capability, records)
        calls = 0

        def enospc_write(descriptor, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(errno.ENOSPC, "synthetic full disk")
            return original_write(descriptor, data[:1])

        with mock.patch.object(MATERIALIZER.os, "write", side_effect=enospc_write):
            with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "write failed"):
                MATERIALIZER.materialize_direct_fetch_once(capability, lease)
        leaf = target / MATERIALIZER._target_record(capability).leaf_basename
        self.assertTrue((leaf / MATERIALIZER.ARTIFACT_BASENAMES[0]).exists())
        self.assertFalse((leaf / MATERIALIZER.MANIFEST_BASENAME).exists())

    def test_no_progress_same_fd_corruption_and_hardlink_race_fail_closed(self) -> None:
        cases = ("no-progress", "same-fd", "hardlink-race")
        for label in cases:
            with self.subTest(label=label):
                target = self.target_root / label
                target.mkdir(mode=0o700)
                _owner, capability = self.target(target)
                lease = MATERIALIZER.issue_offline_synthetic_stream_lease_once(
                    capability, self.payloads
                )
                leaf = target / MATERIALIZER._target_record(capability).leaf_basename
                if label == "no-progress":
                    context = mock.patch.object(MATERIALIZER.os, "write", return_value=0)
                elif label == "same-fd":
                    context = mock.patch.object(
                        MATERIALIZER,
                        "_same_fd_size_hash",
                        return_value=(len(self.payloads[0]), "f" * 64),
                    )
                else:
                    original_fsync = MATERIALIZER.os.fsync
                    linked = False

                    def linking_fsync(descriptor):
                        nonlocal linked
                        result = original_fsync(descriptor)
                        info = os.fstat(descriptor)
                        if stat.S_ISREG(info.st_mode) and not linked:
                            os.link(
                                leaf / MATERIALIZER.ARTIFACT_BASENAMES[0],
                                leaf / "hostile-hardlink",
                            )
                            linked = True
                        return result

                    context = mock.patch.object(
                        MATERIALIZER.os, "fsync", side_effect=linking_fsync
                    )
                with context:
                    with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
                        MATERIALIZER.materialize_direct_fetch_once(capability, lease)
                self.assertTrue(leaf.exists())
                self.assertFalse((leaf / MATERIALIZER.MANIFEST_BASENAME).exists())

    def test_file_directory_and_manifest_fsync_failures_retain_partial(self) -> None:
        for label, failure_call in (("file", 1), ("directory", 6), ("manifest", 7)):
            with self.subTest(label=label):
                target = self.target_root / ("fsync-" + label)
                target.mkdir(mode=0o700)
                _owner, capability = self.target(target)
                lease = MATERIALIZER.issue_offline_synthetic_stream_lease_once(capability, self.payloads)
                original_fsync = MATERIALIZER.os.fsync
                calls = 0

                def failing_fsync(descriptor):
                    nonlocal calls
                    calls += 1
                    if calls == failure_call:
                        raise OSError(errno.EIO, "synthetic fsync failure")
                    return original_fsync(descriptor)

                with mock.patch.object(MATERIALIZER.os, "fsync", side_effect=failing_fsync):
                    with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
                        MATERIALIZER.materialize_direct_fetch_once(capability, lease)
                leaf = target / MATERIALIZER._target_record(capability).leaf_basename
                self.assertTrue(leaf.exists())
                if label in {"file", "directory"}:
                    self.assertFalse((leaf / MATERIALIZER.MANIFEST_BASENAME).exists())
                else:
                    self.assertTrue((leaf / MATERIALIZER.MANIFEST_BASENAME).exists())

    def test_manifest_partial_write_failure_is_not_removed_or_replaced(self) -> None:
        _owner, capability, lease = self.prepared()
        original_write = MATERIALIZER.os.write
        original_open = MATERIALIZER.os.open
        manifest_started = False
        manifest_fd = -1

        def track_manifest_open(path, flags, *args, **kwargs):
            nonlocal manifest_fd
            descriptor = original_open(path, flags, *args, **kwargs)
            if path == MATERIALIZER.MANIFEST_BASENAME:
                manifest_fd = descriptor
            return descriptor

        def partial_manifest(descriptor, data):
            nonlocal manifest_started
            if descriptor == manifest_fd:
                if manifest_started:
                    raise OSError(errno.ENOSPC, "synthetic manifest ENOSPC")
                manifest_started = True
                return original_write(descriptor, data[:11])
            return original_write(descriptor, data)

        with mock.patch.object(MATERIALIZER.os, "open", side_effect=track_manifest_open), \
             mock.patch.object(MATERIALIZER.os, "write", side_effect=partial_manifest), \
             mock.patch.object(MATERIALIZER.os, "unlink", side_effect=AssertionError("delete called")), \
             mock.patch.object(MATERIALIZER.os, "remove", side_effect=AssertionError("delete called")), \
             mock.patch.object(MATERIALIZER.os, "rmdir", side_effect=AssertionError("delete called")), \
             mock.patch.object(MATERIALIZER.os, "rename", side_effect=AssertionError("rename called")), \
             mock.patch.object(MATERIALIZER.os, "replace", side_effect=AssertionError("replace called")):
            with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "write failed"):
                MATERIALIZER.materialize_direct_fetch_once(capability, lease)
        manifest_path = self.leaf(capability) / MATERIALIZER.MANIFEST_BASENAME
        self.assertTrue(manifest_path.exists())
        self.assertEqual(manifest_path.stat().st_size, 11)

    def test_hardlink_fifo_and_device_substitution_are_never_overwritten(self) -> None:
        for label in ("hardlink", "fifo", "device"):
            with self.subTest(label=label):
                target = self.target_root / label
                target.mkdir(mode=0o700)
                _owner, capability = self.target(target)
                lease = MATERIALIZER.issue_offline_synthetic_stream_lease_once(capability, self.payloads)
                leaf = target / MATERIALIZER._target_record(capability).leaf_basename
                original_mkdir = MATERIALIZER.os.mkdir
                original_open = MATERIALIZER.os.open

                def seeded_mkdir(path, mode=0o777, *, dir_fd=None):
                    result = original_mkdir(path, mode=mode, dir_fd=dir_fd)
                    if path == leaf.name:
                        if label == "hardlink":
                            source = leaf / "seed"
                            source.write_bytes(b"do-not-overwrite")
                            os.link(source, leaf / MATERIALIZER.ARTIFACT_BASENAMES[0])
                        elif label == "fifo":
                            os.mkfifo(leaf / MATERIALIZER.ARTIFACT_BASENAMES[0], 0o600)
                    return result

                def device_open(path, flags, *args, **kwargs):
                    if label == "device" and path == MATERIALIZER.ARTIFACT_BASENAMES[0]:
                        return original_open("/dev/null", os.O_WRONLY)
                    return original_open(path, flags, *args, **kwargs)

                with mock.patch.object(MATERIALIZER.os, "mkdir", side_effect=seeded_mkdir), \
                     mock.patch.object(MATERIALIZER.os, "open", side_effect=device_open):
                    with self.assertRaises((MATERIALIZER.DirectLocalFetchMaterializerError, FileExistsError)):
                        MATERIALIZER.materialize_direct_fetch_once(capability, lease)
                self.assertFalse((leaf / MATERIALIZER.MANIFEST_BASENAME).exists())
                if label == "hardlink":
                    self.assertEqual((leaf / MATERIALIZER.ARTIFACT_BASENAMES[0]).read_bytes(), b"do-not-overwrite")
                elif label == "fifo":
                    self.assertTrue(stat.S_ISFIFO(os.lstat(leaf / MATERIALIZER.ARTIFACT_BASENAMES[0]).st_mode))

    def test_second_consume_and_failure_retry_are_forbidden(self) -> None:
        _owner, capability, lease = self.prepared()
        MATERIALIZER.materialize_direct_fetch_once(capability, lease)
        with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "consumed"):
            MATERIALIZER.materialize_direct_fetch_once(capability, lease)

        target = self.target_root / "failed"
        target.mkdir(mode=0o700)
        _owner, capability = self.target(target)
        base = tuple(
            MATERIALIZER._synthetic_record_for_tests(name, raw)
            for name, raw in zip(MATERIALIZER.ARTIFACT_BASENAMES, self.payloads, strict=True)
        )
        bad = list(base)
        bad[0] = MATERIALIZER._synthetic_record_for_tests(base[0].basename, self.payloads[0], declared_sha256="a" * 64)
        lease = MATERIALIZER._issue_synthetic_stream_records_for_tests_once(capability, tuple(bad))
        with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
            MATERIALIZER.materialize_direct_fetch_once(capability, lease)
        with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "consumed"):
            MATERIALIZER.materialize_direct_fetch_once(capability, lease)

    @unittest.skipUnless(hasattr(os, "fork"), "fork revocation requires POSIX fork")
    def test_fork_child_is_revoked_while_parent_remains_current(self) -> None:
        _owner, capability, lease = self.prepared()
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                capability.assert_current()
            except MATERIALIZER.DirectLocalFetchMaterializerError:
                os.write(write_fd, b"revoked")
                os._exit(0)
            os.write(write_fd, b"accepted")
            os._exit(3)
        os.close(write_fd)
        child_result = os.read(read_fd, 32)
        os.close(read_fd)
        _waited, status = os.waitpid(pid, 0)
        self.assertEqual(status, 0)
        self.assertEqual(child_result, b"revoked")
        capability.assert_current()
        lease.assert_current()

    def test_reload_rebind_subclass_and_source_guards_fail_closed(self) -> None:
        source = """
import importlib, pathlib, sys, tempfile
sys.path.insert(0, 'scripts')
import direct_local_fetch_materializer as module
try:
    importlib.reload(module)
except ImportError:
    print('reload-rejected')
else:
    raise SystemExit('reload accepted')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", source],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "reload-rejected")
        with self.assertRaises(TypeError):
            class TargetSubclass(MATERIALIZER.LocalFetchTargetCapability):
                pass
        _owner, capability, lease = self.prepared()
        original = MATERIALIZER.LocalFetchTargetCapability
        try:
            MATERIALIZER.LocalFetchTargetCapability = type("Hostile", (), {})
            with self.assertRaisesRegex(MATERIALIZER.DirectLocalFetchMaterializerError, "binding differs"):
                lease.assert_current()
        finally:
            MATERIALIZER.LocalFetchTargetCapability = original
        capability.assert_current()

    def test_source_contains_no_delete_cleanup_rename_or_network_operations(self) -> None:
        source = (SCRIPTS / "direct_local_fetch_materializer.py").read_text(encoding="utf-8")
        for forbidden in (
            "os.unlink(", "os.remove(", "os.rmdir(", "os.rename(", "os.replace(",
            "shutil.rmtree(", "socket.", "subprocess.", "import socket", "import subprocess",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
