#!/usr/bin/env python3
"""Execute base and candidate legacy stage behavior against the same cases."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
LEGACY_PATH = (
    ROOT / "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py"
)
BASE_COMMIT = "70f1575219eecf8864722d91282c9e0902681ef8"
LARGE_SIZE = 16 * 1024 * 1024 + 4096
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(LEGACY_PATH.parent))


def _common_git_dir() -> Path:
    dot_git = ROOT / ".git"
    if dot_git.is_dir():
        return dot_git
    raw = dot_git.read_text(encoding="utf-8").strip()
    if not raw.startswith("gitdir: "):
        raise RuntimeError("worktree Git metadata is unavailable")
    worktree_git = Path(raw.removeprefix("gitdir: ")).resolve()
    common = (worktree_git / "commondir").read_text(
        encoding="utf-8"
    ).strip()
    return (worktree_git / common).resolve()


def _base_source() -> bytes:
    result = subprocess.run(
        [
            "git",
            f"--git-dir={_common_git_dir()}",
            "show",
            f"{BASE_COMMIT}:skills/auto-g16-rtwin-pbs/scripts/"
            "legacy_rtwin_pbs.py",
        ],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _runtime_module() -> types.ModuleType:
    module = types.ModuleType("runtime_config")
    module.setting = (  # type: ignore[attr-defined]
        lambda env_name, key, default: os.environ.get(env_name, default)
    )
    return module


def _load(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        with mock.patch.dict(
            sys.modules,
            {"runtime_config": _runtime_module()},
        ):
            spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    module.utc_now = lambda: "2030-01-01T12:00:00Z"
    return module


def _normal_input(path: Path) -> None:
    path.write_text(
        "%chk=job.chk\n"
        "%mem=12GB\n"
        "%nprocshared=8\n"
        "#p hf/sto-3g opt\n\n"
        "placeholder differential\n\n"
        "0 1\n"
        "H 0 0 0\n\n",
        encoding="utf-8",
    )


def _allcheck_input(path: Path, *, checkpoint_exists: bool) -> None:
    path.write_text(
        "%chk=job.chk\n"
        "%oldchk=old.chk\n"
        "%mem=12GB\n"
        "%nprocshared=8\n"
        "#p hf/sto-3g geom=allcheck guess=read\n\n",
        encoding="utf-8",
    )
    checkpoint = path.parent / "old.chk"
    checkpoint_hash = hashlib.sha256(b"missing-placeholder").hexdigest()
    if checkpoint_exists:
        with checkpoint.open("wb") as handle:
            remaining = LARGE_SIZE
            chunk = b"large-placeholder-checkpoint\n" * 4096
            hasher = hashlib.sha256()
            while remaining:
                part = chunk[:remaining]
                handle.write(part)
                hasher.update(part)
                remaining -= len(part)
        checkpoint_hash = hasher.hexdigest()
    manifest = {
        "schema": "gaussian-allcheck-input-manifest/1",
        "geometry_source": "geom_allcheck_from_reviewed_checkpoint",
        "no_explicit_molecule_specification": True,
        "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "checkpoint_file": "old.chk",
        "checkpoint_sha256": checkpoint_hash,
        "charge": 0,
        "multiplicity": 1,
        "atom_count": 1,
        "atom_order": [
            {"index": 1, "element": "H", "atomic_number": 1}
        ],
        "warnings": [],
    }
    path.with_suffix(".json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def _tree(path: Path) -> list[tuple[str, int, str]]:
    if not path.exists():
        return []
    result = []
    for item in sorted(path.rglob("*")):
        if item.is_file() and not item.is_symlink():
            data = item.read_bytes()
            result.append(
                (
                    item.relative_to(path).as_posix(),
                    len(data),
                    hashlib.sha256(data).hexdigest(),
                )
            )
        elif item.is_symlink():
            result.append(
                (
                    item.relative_to(path).as_posix(),
                    -1,
                    f"symlink:{os.readlink(item)}",
                )
            )
    return result


def _normalize(value: object, root: Path) -> object:
    if isinstance(value, str):
        return value.replace(str(root), "<CASE_ROOT>")
    if isinstance(value, dict):
        return {
            key: _normalize(item, root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize(item, root) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item, root) for item in value)
    return value


def _run(module: types.ModuleType, root: Path, case: str) -> dict[str, object]:
    source = root / "source"
    target = root / "target"
    source.mkdir(parents=True)
    input_path = source / "job.gjf"
    if case in {"large_checkpoint", "missing_oldchk", "checkpoint_conflict"}:
        _allcheck_input(
            input_path,
            checkpoint_exists=case != "missing_oldchk",
        )
    else:
        _normal_input(input_path)
    if case == "large_companion":
        with input_path.with_suffix(".xyz").open("wb") as handle:
            handle.write(b"0\nplaceholder\n")
            handle.truncate(LARGE_SIZE)
    elif case in {"companion_conflict", "resource_failure"}:
        input_path.with_suffix(".xyz").write_text(
            "1\nplaceholder\nH 0 0 0\n",
            encoding="utf-8",
        )

    if case.endswith("_conflict"):
        target.mkdir()
        name = {
            "input_conflict": "job.gjf",
            "companion_conflict": "job.xyz",
            "checkpoint_conflict": "old.chk",
        }[case]
        (target / name).write_bytes(b"different existing target")

    resources = {
        "resource_tier": "simple",
        "cores": 8,
        "memory_gb": 12,
        "walltime_seconds": 3600,
    }
    if case == "resource_failure":
        resources["memory_gb"] = 50
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            job, files = module.stage(
                input_path,
                "diffjob",
                target,
                resources,
            )
    except BaseException as exc:
        outcome: dict[str, object] = {
            "status": "error",
            "type": type(exc).__name__,
            "code": exc.code if isinstance(exc, SystemExit) else None,
            "stderr": stderr.getvalue(),
        }
    else:
        outcome = {
            "status": "ok",
            "job": job,
            "files": [item.name for item in files],
        }
    outcome["target_tree"] = _tree(target)
    return _normalize(outcome, root)  # type: ignore[return-value]


class LegacyStageDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / ".git").exists():
            raise unittest.SkipTest(
                "historical legacy differential requires Git metadata"
            )
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-legacy-stage-differential-",
        )
        cls.root = (
            Path(cls.temporary.name).resolve()
            / "repository"
            / "skills"
            / "auto-g16-rtwin-pbs"
            / "scripts"
        )
        cls.root.mkdir(parents=True)
        base_path = cls.root / "legacy_base.py"
        base_path.write_bytes(_base_source())
        cls.base = _load("auto_g16_legacy_stage_base", base_path)
        cls.candidate = _load(
            "auto_g16_legacy_stage_candidate",
            LEGACY_PATH,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_base_and_candidate_stage_behavior_are_identical(self) -> None:
        cases = (
            "large_companion",
            "large_checkpoint",
            "missing_oldchk",
            "input_conflict",
            "companion_conflict",
            "checkpoint_conflict",
            "resource_failure",
        )
        for case in cases:
            with self.subTest(case=case):
                shared_root = self.root / case / "shared"
                base = _run(self.base, shared_root, case)
                shutil.rmtree(shared_root)
                self.assertEqual(
                    base,
                    _run(self.candidate, shared_root, case),
                )


if __name__ == "__main__":
    unittest.main()
