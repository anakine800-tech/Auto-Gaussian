#!/usr/bin/env python3
"""Owner-selected fixed repository/named-package bootstrap for sshd subsystems."""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import json
import os
import stat
import sys
import types
from pathlib import Path
from typing import Any


INVENTORY_SCHEMA = "auto-g16-direct-subsystem-source-inventory/1"
NAMED_SKILL = "auto-g16-rtwin-pbs"
INVENTORY_BASENAME = "direct-subsystem-source-inventory.json"
SUBMIT_ENTRYPOINT = "direct_submit_subsystem_entrypoint.py"
READ_ENTRYPOINT = "direct_read_subsystem_entrypoint.py"
INVENTORY_SOURCE_SHA256 = "20f51e6ba7504c6bff42ba7c0319e36de73190db20fd504bbcd0e6a4e528ec78"
_OUTER_ANCHOR_EXCLUSIONS = (
    "contracts/direct-execution/direct-subsystem-source-inventory.json",
    "scripts/direct_read_subsystem_entrypoint.py",
    "scripts/direct_submit_subsystem_entrypoint.py",
    "scripts/direct_subsystem_bootstrap.py",
)
_REPOSITORY_SCRIPT_ROOTS = (
    "scripts",
    "skills/auto-g16-rtwin-pbs/scripts",
)
_REPOSITORY_OUTER_ANCHORS = _OUTER_ANCHOR_EXCLUSIONS[1:]
_PRODUCTION_PREDECESSOR_LOAD_ORDER = (
    "runtime_config",
    "execution_facade",
    "legacy_rtwin_pbs",
    "protected_lifecycle_contract",
    "protected_local_materialization",
    "protected_legacy_effect_handoff",
    "protected_runtime_state_contract",
    "protected_owner_consumer_contract",
    "protected_production_ingress_contract",
    "direct_effect_time_replay_ingress",
    "direct_one_hop_transport",
)
_SUBMIT_LOAD_ORDER = _PRODUCTION_PREDECESSOR_LOAD_ORDER
_READ_LOAD_ORDER = (
    *_PRODUCTION_PREDECESSOR_LOAD_ORDER,
    "direct_read_subsystem_dispatcher",
    "direct_qstat_acquisition",
    "direct_fetch_acquisition",
)


class DirectSubsystemBootstrapError(ImportError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectSubsystemBootstrapError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)


def _open_absolute_directory_chain(path: Path) -> tuple[int, tuple[tuple[str, tuple[int, ...]], ...]]:
    absolute = Path(os.path.abspath(path))
    _require(absolute.is_absolute(), "subsystem package root must be absolute")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    opened: list[int] = []
    chain: list[tuple[str, tuple[int, ...]]] = []
    try:
        current = Path("/")
        for part in absolute.parts[1:]:
            descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
            opened.append(descriptor)
            current /= part
            chain.append((str(current), _directory_identity(os.fstat(descriptor))))
            os.close(parent)
            parent = os.dup(descriptor)
        _require(bool(opened), "subsystem package root cannot be filesystem root")
        retained = os.dup(opened[-1])
        return retained, tuple(chain)
    except BaseException:
        raise
    finally:
        os.close(parent)
        for descriptor in opened:
            os.close(descriptor)


def _replay_absolute_directory_chain(
    path: Path, expected: tuple[tuple[str, tuple[int, ...]], ...],
) -> None:
    descriptor, observed = _open_absolute_directory_chain(path)
    try:
        _require(observed == expected, "subsystem package-root identity changed")
    finally:
        os.close(descriptor)


def _relative_stat(root_fd: int, relative: str) -> os.stat_result | None:
    parts = Path(relative).parts
    parent = os.dup(root_fd)
    try:
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            if not final:
                flags |= os.O_DIRECTORY
            descriptor = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = descriptor
        return os.fstat(parent)
    except FileNotFoundError:
        return None
    finally:
        os.close(parent)


def _relative_kind(root_fd: int, relative: str) -> str:
    try:
        info = os.stat(relative, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return "absent"
    if stat.S_ISLNK(info.st_mode):
        return "symlink"
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    if stat.S_ISREG(info.st_mode):
        return "file"
    return "other"


def _layout() -> tuple[str, Path, int, tuple[tuple[str, tuple[int, ...]], ...], str]:
    source = Path(os.path.abspath(__file__))
    root = source.parent.parent
    root_fd, root_chain = _open_absolute_directory_chain(root)
    repository_paths = ("skills", f"skills/{NAMED_SKILL}", f"skills/{NAMED_SKILL}/scripts")
    kinds = {path: _relative_kind(root_fd, path) for path in repository_paths}
    repository_shape = any(kind != "absent" for kind in kinds.values())
    repository_complete = (
        kinds["skills"] == "directory"
        and kinds[f"skills/{NAMED_SKILL}"] == "directory"
        and kinds[f"skills/{NAMED_SKILL}/scripts"] == "directory"
        and _relative_kind(root_fd, f"skills/{NAMED_SKILL}/SKILL.md") == "file"
    )
    named_shape = root.name == NAMED_SKILL and (
        _relative_kind(root_fd, "SKILL.md") != "absent"
        or _relative_kind(root_fd, "scripts") != "absent"
    )
    named_complete = (named_shape and _relative_kind(root_fd, "scripts") == "directory"
                      and _relative_kind(root_fd, "SKILL.md") == "file")
    _require(not any(kind in {"symlink", "other"} for kind in kinds.values()),
             "subsystem layout contains a symlink or special object")
    _require(not ((repository_shape and not repository_complete)
                  or (named_shape and not named_complete)), "subsystem layout is partial")
    _require(repository_complete != named_complete, "exactly one subsystem layout is required")
    inventory = "contracts/direct-execution/" + INVENTORY_BASENAME
    return ("repository" if repository_complete else "named-skill",
            root, root_fd, root_chain, inventory)


def _snapshot_relative(root_fd: int, relative: str) -> tuple[tuple[int, ...], str, bytes]:
    parts = Path(relative).parts
    _require(bool(parts) and not relative.startswith("/") and ".." not in parts,
             "subsystem relative source differs")
    parent = os.dup(root_fd)
    descriptor = -1
    try:
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            if not final:
                flags |= os.O_DIRECTORY
            descriptor = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = descriptor
        before = os.fstat(parent)
        _require(stat.S_ISREG(before.st_mode), "subsystem source is not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(parent, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(parent)
    finally:
        os.close(parent)
    identity = _identity(before)
    _require(identity == _identity(after), "subsystem source identity changed")
    raw = b"".join(chunks)
    return identity, hashlib.sha256(raw).hexdigest(), raw


def _walk_package_files(root_fd: int) -> dict[str, str]:
    observed: dict[str, str] = {}

    def walk(directory_fd: int, prefix: str) -> None:
        for name in sorted(os.listdir(directory_fd)):
            _require("/" not in name and name not in {".", ".."},
                     "named package entry differs")
            relative = name if not prefix else f"{prefix}/{name}"
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            _require(not stat.S_ISLNK(info.st_mode), "named package contains a symlink")
            _require(name != "__pycache__", "named package contains Python bytecode")
            if stat.S_ISDIR(info.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory_fd,
                )
                try:
                    walk(child, relative)
                finally:
                    os.close(child)
            else:
                _require(stat.S_ISREG(info.st_mode),
                         "named package contains a non-regular object")
                _require(
                    "__pycache__" not in Path(relative).parts
                    and not relative.endswith((".pyc", ".pyo")),
                    "named package contains Python bytecode",
                )
                _entry_identity, entry_sha, _entry_raw = _snapshot_relative(root_fd, relative)
                observed[relative] = entry_sha

    walk(root_fd, "")
    return observed


def _walk_repository_script_roots(root_fd: int) -> dict[str, str]:
    observed: dict[str, str] = {}

    def walk(directory_fd: int, prefix: str) -> None:
        for name in sorted(os.listdir(directory_fd)):
            _require("/" not in name and name not in {"", ".", ".."},
                     "repository scripts entry differs")
            relative = f"{prefix}/{name}"
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            _require(not stat.S_ISLNK(info.st_mode),
                     "repository scripts contains a symlink")
            _require(name != "__pycache__" and not name.endswith((".pyc", ".pyo")),
                     "repository scripts contains Python bytecode")
            if stat.S_ISDIR(info.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory_fd,
                )
                try:
                    walk(child, relative)
                finally:
                    os.close(child)
            else:
                _require(stat.S_ISREG(info.st_mode),
                         "repository scripts contains a non-regular object")
                _entry_identity, entry_sha, _entry_raw = _snapshot_relative(
                    root_fd, relative
                )
                observed[relative] = entry_sha

    for scripts_root in _REPOSITORY_SCRIPT_ROOTS:
        directory_fd = os.dup(root_fd)
        try:
            for part in Path(scripts_root).parts:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = child
            walk(directory_fd, scripts_root)
        finally:
            os.close(directory_fd)
    return observed


def _load_inventory(
    *, bound_root_fd: int | None = None,
    enforce_repository_projection: bool = False,
) -> tuple[
    str, Path, int, tuple[tuple[str, tuple[int, ...]], ...],
    dict[str, tuple[Path, str, tuple[int, ...], bytes]], str,
]:
    layout, root, selected_root_fd, root_chain, inventory_relative = _layout()
    if bound_root_fd is None:
        root_fd = selected_root_fd
    else:
        _require(type(bound_root_fd) is int and bound_root_fd >= 3,
                 "bound subsystem package root descriptor differs")
        selected = os.fstat(selected_root_fd)
        bound = os.fstat(bound_root_fd)
        os.close(selected_root_fd)
        _require(
            _directory_identity(selected) == _directory_identity(bound),
            "bound subsystem package root identity differs",
        )
        root_fd = os.dup(bound_root_fd)
    _require(_relative_kind(root_fd, inventory_relative) == "file",
             "subsystem source inventory is absent")
    _inventory_identity, _inventory_sha, raw = _snapshot_relative(
        root_fd, inventory_relative
    )
    _require(
        INVENTORY_SOURCE_SHA256 != "0" * 64
        and _inventory_sha == INVENTORY_SOURCE_SHA256,
        "subsystem inventory source SHA differs",
    )
    try:
        inventory = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectSubsystemBootstrapError("subsystem inventory is not exact JSON") from exc
    _require(type(inventory) is dict and set(inventory) == {
        "schema", "skill", "files", "package_projection",
        "repository_scripts_projection", "authorizes_apply",
        "inventory_payload_sha256"},
        "subsystem inventory fields differ")
    supplied = inventory["inventory_payload_sha256"]
    _require(inventory["schema"] == INVENTORY_SCHEMA and inventory["skill"] == NAMED_SKILL
             and inventory["authorizes_apply"] is False and type(supplied) is str
             and len(supplied) == 64 and supplied != "0" * 64
             and supplied == hashlib.sha256(_canonical({**inventory,
                 "inventory_payload_sha256": ""})).hexdigest()
             and raw == _canonical(inventory) + b"\n", "subsystem inventory bytes or hash differ")
    _require(type(inventory["files"]) is list and bool(inventory["files"]),
             "subsystem inventory is empty")
    repository_parents: set[str] = set()
    for item in inventory["files"]:
        _require(type(item) is dict and set(item) == {
            "module", "repository_path", "named_path", "sha256"
        }, "subsystem inventory entry differs")
        for field in ("repository_path", "named_path"):
            relative = item[field]
            _require(type(relative) is str and bool(relative)
                     and not relative.startswith("/")
                     and ".." not in Path(relative).parts,
                     "subsystem inventory module or path differs")
        repository_parents.add(str(Path(item["repository_path"]).parent))
    _require(
        tuple(sorted(repository_parents)) == _REPOSITORY_SCRIPT_ROOTS,
        "subsystem inventory repository script roots differ",
    )
    repository_projection = inventory["repository_scripts_projection"]
    _require(type(repository_projection) is dict and set(repository_projection) == {
        "schema", "roots", "excluded_sources", "file_count",
        "source_sha256_map_sha256"
    }
        and repository_projection["schema"]
        == "auto-g16-repository-scripts-projection/1"
        and type(repository_projection["roots"]) is list
        and tuple(repository_projection["roots"]) == _REPOSITORY_SCRIPT_ROOTS
        and type(repository_projection["excluded_sources"]) is list
        and tuple(repository_projection["excluded_sources"])
        == _REPOSITORY_OUTER_ANCHORS
        and type(repository_projection["file_count"]) is int
        and repository_projection["file_count"] > 0
        and type(repository_projection["source_sha256_map_sha256"]) is str
        and len(repository_projection["source_sha256_map_sha256"]) == 64,
        "repository scripts projection differs")
    if layout == "repository" and enforce_repository_projection:
        repository_observed = _walk_repository_script_roots(root_fd)
        _require(
            set(_REPOSITORY_OUTER_ANCHORS).issubset(repository_observed),
            "repository outer anchors are absent",
        )
        for relative in _REPOSITORY_OUTER_ANCHORS:
            repository_observed.pop(relative)
        _require(
            len(repository_observed) == repository_projection["file_count"]
            and hashlib.sha256(_canonical(repository_observed)).hexdigest()
            == repository_projection["source_sha256_map_sha256"],
            "repository scripts inventory missing, changed, or extra",
        )
    package_projection = inventory["package_projection"]
    _require(type(package_projection) is dict and set(package_projection) == {
        "schema", "excluded_targets", "file_count", "target_sha256_map_sha256"}
        and package_projection["schema"] == "auto-g16-named-package-projection/1"
        and type(package_projection["excluded_targets"]) is list
        and tuple(package_projection["excluded_targets"]) == _OUTER_ANCHOR_EXCLUSIONS
        and type(package_projection["file_count"]) is int
        and package_projection["file_count"] > 0
        and type(package_projection["target_sha256_map_sha256"]) is str
        and len(package_projection["target_sha256_map_sha256"]) == 64,
        "named-package projection differs")
    if layout == "named-skill":
        observed = _walk_package_files(root_fd)
        for relative in package_projection["excluded_targets"]:
            observed.pop(relative, None)
        _require(len(observed) == package_projection["file_count"]
                 and hashlib.sha256(_canonical(observed)).hexdigest()
                 == package_projection["target_sha256_map_sha256"],
                 "named-package inventory missing, changed, or extra")
    bindings: dict[str, tuple[Path, str, tuple[int, ...], bytes]] = {}
    for item in inventory["files"]:
        module = item["module"]
        relative = item["repository_path"] if layout == "repository" else item["named_path"]
        _require(type(module) is str and module not in bindings and type(relative) is str
                 and not relative.startswith("/") and ".." not in Path(relative).parts,
                 "subsystem inventory module or path differs")
        _require(_relative_kind(root_fd, relative) == "file",
                 f"subsystem inventory source is absent: {module}")
        path = root / relative
        identity, observed, source_raw = _snapshot_relative(root_fd, relative)
        _require(observed == item["sha256"], f"subsystem reviewed source SHA differs: {module}")
        bindings[module] = (path, observed, identity, source_raw)
    _require({"direct_one_hop_transport",
              "direct_read_subsystem_dispatcher"}.issubset(bindings),
             "subsystem inventory lacks fixed production owners")
    _replay_absolute_directory_chain(root, root_chain)
    attestation = hashlib.sha256(_canonical({
        "schema": "auto-g16-reviewed-subsystem-source-attestation/1",
        "layout": layout,
        "inventory_payload_sha256": supplied,
        "files": [
            {
                "module": name,
                "path": str(path.relative_to(root)),
                "sha256": source_sha256,
                "identity": list(identity),
            }
            for name, (path, source_sha256, identity, _source_raw)
            in sorted(bindings.items())
        ],
    })).hexdigest()
    return layout, root, root_fd, root_chain, bindings, attestation


def review_inventory_attestation() -> str:
    _layout_name, _root, root_fd, _root_chain, _bindings, attestation = _load_inventory()
    os.close(root_fd)
    return attestation


def _assert_clean_process(
    bindings: dict[str, tuple[Path, str, tuple[int, ...], bytes]],
) -> None:
    _require(sys.flags.isolated == 1 and sys.flags.no_site == 1 and sys.dont_write_bytecode
             and Path.cwd() == Path("/") and os.environ.get("LANG") == "C"
             and os.environ.get("LC_ALL") == "C"
             and "PYTHONPATH" not in os.environ and "PYTHONHOME" not in os.environ,
             "subsystem requires fixed -I -S -B cwd/environment")
    allowed = {__name__}
    _require(not any(name in sys.modules and name not in allowed for name in bindings),
             "subsystem dependency was preloaded")


class _ReviewedSourceLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(
        self, bindings: dict[str, tuple[Path, str, tuple[int, ...], bytes]],
    ) -> None:
        self._bindings = bindings
        self.executed: list[str] = []

    def find_spec(self, fullname: str, _path: Any = None, _target: Any = None) -> Any:
        if fullname not in self._bindings:
            return None
        origin = str(self._bindings[fullname][0])
        return importlib.util.spec_from_loader(fullname, self, origin=origin)

    def create_module(self, _spec: Any) -> None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        name = module.__name__
        _require(name in self._bindings and name not in self.executed,
                 "reviewed subsystem module execution differs")
        path, reviewed_sha, _identity_value, source_raw = self._bindings[name]
        _require(hashlib.sha256(source_raw).hexdigest() == reviewed_sha,
                 "reviewed subsystem source bytes drifted")
        module.__file__ = str(path)
        module.__reviewed_source_sha256__ = reviewed_sha
        self.executed.append(name)
        exec(compile(source_raw, str(path), "exec", dont_inherit=True), module.__dict__)


def _import_target(
    module_name: str, *, bound_root_fd: int | None = None,
    expected_inventory_attestation_sha256: str | None = None,
) -> types.ModuleType:
    _layout_name, root, root_fd, root_chain, bindings, attestation = _load_inventory(
        bound_root_fd=bound_root_fd,
        enforce_repository_projection=True,
    )
    try:
        _require(
            expected_inventory_attestation_sha256 is None
            or (
                type(expected_inventory_attestation_sha256) is str
                and len(expected_inventory_attestation_sha256) == 64
                and expected_inventory_attestation_sha256 == attestation
            ),
            "subsystem inventory/source identity attestation differs",
        )
        _assert_clean_process(bindings)
        loader = _ReviewedSourceLoader(bindings)
        sys.meta_path.insert(0, loader)
        load_order = _SUBMIT_LOAD_ORDER if module_name == "direct_one_hop_transport" else _READ_LOAD_ORDER
        loaded = {}
        for name in load_order:
            loaded[name] = importlib.import_module(name)
        module = loaded[module_name]
    finally:
        while "loader" in locals() and loader in sys.meta_path:
            sys.meta_path.remove(loader)
    _require(type(module) is types.ModuleType and module_name in bindings,
             "subsystem target module differs")
    expected, _sha, _identity_value, _source_raw = bindings[module_name]
    _require(Path(module.__file__) == expected, "subsystem target origin differs")
    for name, (path, _reviewed_sha, _reviewed_identity, _reviewed_raw) in bindings.items():
        imported = sys.modules.get(name)
        if imported is not None:
            if name == __name__:
                _require(
                    imported is sys.modules.get(__name__)
                    and type(imported) is types.ModuleType
                    and Path(imported.__file__) == path
                    and getattr(imported, "__reviewed_source_sha256__", None)
                    == _reviewed_sha
                    and hashlib.sha256(_reviewed_raw).hexdigest() == _reviewed_sha,
                    "subsystem bootstrap origin differs",
                )
                continue
            _require(type(imported) is types.ModuleType
                     and Path(imported.__file__) == path and name in loader.executed,
                     f"subsystem dependency origin differs: {name}")
    _replay_absolute_directory_chain(root, root_chain)
    os.close(root_fd)
    return module


def submit_main() -> int:
    _require(sys.argv[1:] == [], "submit subsystem argv is closed")
    module = _import_target("direct_one_hop_transport")
    return module.server_subsystem_once()


def read_main() -> int:
    _require(sys.argv[1:] == [], "read subsystem argv is closed")
    module = _import_target("direct_read_subsystem_dispatcher")
    return module.main(["--fixed-read-subsystem"])
