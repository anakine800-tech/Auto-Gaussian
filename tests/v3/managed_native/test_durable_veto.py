"""Durability adapter call order, not fsync/crash or filesystem qualification."""
from contextlib import contextmanager
import os
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from auto_g16._managed_native import lifecycle
from auto_g16._managed_offline.common import Rejected


class Model:
    def __init__(self, failure=None):
        self.calls, self.body, self.failure = [], b"", failure
        self.chain = ((1, 1), (1, 2))
        self.links = 1
        self.tampered = False
        self.ops = SimpleNamespace(**{k:getattr(os,k) for k in ("O_RDWR","O_CREAT","O_EXCL","O_NOFOLLOW","O_CLOEXEC")}, dup=self.dup, set_inheritable=self.inherit, fstat=self.info, stat=self.named, open=self.open, write=self.write, fsync=self.sync, pread=self.read)
        self.fcntl = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, F_FULLFSYNC=51, flock=self.lock, fcntl=self.full)
    def step(self, name):
        self.calls.append(name)
        if name == self.failure: raise OSError("injected " + name)
    @contextmanager
    def parent(self, path):
        self.step("parent")
        yield 20, "lock", self.chain
    def dup(self, fd): self.step("dup"); return 21
    def inherit(self, fd, value):
        self.step("cloexec")
        if value: raise AssertionError("inherited fd")
    def info(self, fd):
        return SimpleNamespace(st_dev=1, st_ino=20 if fd in (20,21) else fd, st_mode=(stat.S_IFDIR|0o700) if fd in (20,21) else (stat.S_IFREG|0o600), st_uid=701, st_gid=701, st_nlink=self.links)
    def named(self, name, *, dir_fd, follow_symlinks):
        if follow_symlinks: raise AssertionError("follow")
        result = self.info(30 if name == "lock" else 31)
        if self.tampered: result.st_ino += 1
        return result
    def open(self, name, flags, mode=None, *, dir_fd):
        self.step("open_" + name)
        required = os.O_NOFOLLOW | os.O_CLOEXEC
        if name == "lifetime-used": required |= os.O_CREAT | os.O_EXCL
        if flags & required != required: raise AssertionError("unsafe flags")
        return 30 if name == "lock" else 31
    def lock(self, fd, flags): self.step("flock")
    def write(self, fd, data):
        self.step("write")
        if self.failure == "zero_write": return 0
        chunk = data[:11]; self.body += chunk; return len(chunk)
    def sync(self, fd): self.step("fsync_file" if fd==31 else "fsync_parent")
    def full(self, fd, command): self.step("fullfsync")
    def read(self, fd, count, offset): self.step("pread"); return self.body


class DurableVetoTests(unittest.TestCase):
    def construct(self, model):
        installation = SimpleNamespace(state="/private/var/db/auto-g16/inert", executor_uid=701, description_sha256="a"*64)
        return lifecycle.DurableVeto(installation)

    def test_partial_write_and_sync_order_before_ready(self):
        model = Model(); veto = self.construct(model)
        with patch.object(lifecycle, "os", model.ops), patch.object(lifecycle, "fcntl", model.fcntl), patch.object(lifecycle, "_direct_parent", model.parent):
            life = lifecycle.Lifecycle(veto.installation, veto)
            self.assertEqual(life.state, "READY_CLOSED")
            self.assertEqual(model.body, veto.body)
            calls = model.calls
            self.assertLess(calls.index("flock"), calls.index("open_lifetime-used"))
            self.assertGreater(calls.count("write"), 1)
            self.assertLess(max(i for i,x in enumerate(calls) if x=="write"), calls.index("fsync_file"))
            self.assertLess(calls.index("fsync_file"), calls.index("fsync_parent"))
            self.assertLess(calls.index("fsync_parent"), calls.index("fullfsync"))
            self.assertLess(calls.index("fullfsync"), calls.index("pread"))
            before = list(calls)
            with self.assertRaises(Rejected): veto.establish()
            self.assertEqual(calls, before)

    def test_each_failed_stage_cannot_retry_same_owner(self):
        for stage in ("parent", "dup", "cloexec", "open_lock", "flock", "open_lifetime-used", "write", "zero_write", "fsync_file", "fsync_parent", "fullfsync", "pread"):
            with self.subTest(stage=stage):
                model = Model(stage); veto = self.construct(model)
                with patch.object(lifecycle, "os", model.ops), patch.object(lifecycle, "fcntl", model.fcntl), patch.object(lifecycle, "_direct_parent", model.parent):
                    with self.assertRaises((OSError, Rejected)): veto.establish()
                    previous = list(model.calls); model.failure = None
                    with self.assertRaises(Rejected): veto.establish()
                    self.assertEqual(model.calls, previous)
                    self.assertNotIn("unlink", model.calls)

    def test_missing_full_flush_is_rejection(self):
        model = Model(); del model.fcntl.F_FULLFSYNC
        with patch.object(lifecycle, "os", model.ops), patch.object(lifecycle, "fcntl", model.fcntl), patch.object(lifecycle, "_direct_parent", model.parent):
            with self.assertRaises(Rejected): self.construct(model).establish()
            self.assertNotIn("pread", model.calls)

    def test_chain_leaf_and_link_drift_permanently_poison(self):
        for attack in ("chain", "leaf", "links", "body"):
            with self.subTest(attack=attack):
                model = Model(); veto = self.construct(model)
                with patch.object(lifecycle, "os", model.ops), patch.object(lifecycle, "fcntl", model.fcntl), patch.object(lifecycle, "_direct_parent", model.parent):
                    life = lifecycle.Lifecycle(veto.installation, veto)
                    chain, body = model.chain, model.body
                    if attack == "chain": model.chain = ((9,9),)
                    if attack == "leaf": model.tampered = True
                    if attack == "links": model.links = 2
                    if attack == "body": model.body = b"changed"
                    with self.assertRaises(Rejected): life.manage("OPEN", peer_uid=0)
                    model.chain, model.body, model.tampered, model.links = chain, body, False, 1
                    self.assertEqual(life.state, "BLOCKED")
                    with self.assertRaises(Rejected): life.manage("OPEN", peer_uid=0)
