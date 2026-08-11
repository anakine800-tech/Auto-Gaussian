#!/usr/bin/env python3
"""Fixed production read sshd Subsystem entrypoint."""
from __future__ import annotations
import hashlib
import importlib.util
import os
import stat
import sys
import types
from pathlib import Path

_REVIEWED_BOOTSTRAP_SHA256 = "14038929627c380fa145dafce8d3919a851e55a530caeb4ac6b77de3ad197b09"
_SOURCE = Path(os.path.abspath(__file__)).parent / "direct_subsystem_bootstrap.py"
_ENTRY_PATH = Path(os.path.abspath(__file__))
_REGISTRY_KEY = "_auto_g16_direct_read_subsystem_entrypoint_v1"
if getattr(sys, _REGISTRY_KEY, None) is not None:
    raise ImportError("read subsystem entrypoint was reloaded")
_ENTRY_TOKEN = object()
_ENTRY_STATE = (_ENTRY_TOKEN, os.getpid(), id(globals()), str(_ENTRY_PATH))
setattr(sys, _REGISTRY_KEY, _ENTRY_STATE)
_FROZEN_MODULE = sys.modules.get(__name__)


def _open_nofollow_source() -> tuple[int, tuple[tuple[int, ...], ...]]:
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    chain = []
    try:
        parts = _SOURCE.parts[1:]
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            if not final:
                flags |= os.O_DIRECTORY
            descriptor = os.open(part, flags, dir_fd=parent)
            info = os.fstat(descriptor)
            chain.append((info.st_dev, info.st_ino, info.st_uid, info.st_gid,
                          info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            os.close(parent)
            parent = descriptor
        return parent, tuple(chain)
    except BaseException:
        os.close(parent)
        raise


def _load_reviewed_bootstrap() -> types.ModuleType:
    if "direct_subsystem_bootstrap" in sys.modules:
        raise ImportError("fixed subsystem bootstrap was preloaded")
    descriptor, source_chain = _open_nofollow_source()
    try:
        before = os.fstat(descriptor)
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    replay_descriptor, replay_chain = _open_nofollow_source()
    os.close(replay_descriptor)
    identity = (before.st_dev, before.st_ino, before.st_uid, before.st_gid,
                before.st_mode, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    if (not stat.S_ISREG(before.st_mode)
            or identity != (after.st_dev, after.st_ino, after.st_uid, after.st_gid,
                            after.st_mode, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or hashlib.sha256(raw).hexdigest() != _REVIEWED_BOOTSTRAP_SHA256):
        raise ImportError("fixed subsystem bootstrap identity differs")
    if replay_chain != source_chain:
        raise ImportError("fixed subsystem bootstrap component identity changed")
    os.chdir("/")
    os.environ.clear()
    os.environ.update({"LANG": "C", "LC_ALL": "C"})
    spec = importlib.util.spec_from_loader(
        "direct_subsystem_bootstrap", loader=None, origin=str(_SOURCE)
    )
    module = types.ModuleType("direct_subsystem_bootstrap")
    module.__file__ = str(_SOURCE)
    module.__spec__ = spec
    module.__reviewed_source_sha256__ = _REVIEWED_BOOTSTRAP_SHA256
    sys.modules["direct_subsystem_bootstrap"] = module
    exec(compile(raw, str(_SOURCE), "exec", dont_inherit=True), module.__dict__)
    return module


def main() -> int:
    if (sys.argv[1:] != [] or globals().get("_FROZEN_MAIN") is not main
            or globals().get("_load_reviewed_bootstrap") is not _FROZEN_BOOTSTRAP_LOADER
            or globals().get("_open_nofollow_source") is not _FROZEN_SOURCE_OPENER
            or __name__ != "__main__" or sys.modules.get("__main__") is not _FROZEN_MODULE
            or getattr(_FROZEN_MODULE, "__dict__", None) is not globals()
            or getattr(sys, _REGISTRY_KEY, None) != _ENTRY_STATE
            or _ENTRY_STATE != (_ENTRY_TOKEN, os.getpid(), id(globals()), str(_ENTRY_PATH))
            or Path(os.path.abspath(sys.argv[0])) != _ENTRY_PATH):
        raise ImportError("read subsystem argv is closed")
    module = _load_reviewed_bootstrap()
    return module.read_main()


_FROZEN_SOURCE_OPENER = _open_nofollow_source
_FROZEN_BOOTSTRAP_LOADER = _load_reviewed_bootstrap
_FROZEN_MAIN = main

if __name__ == "__main__":
    raise SystemExit(main())
