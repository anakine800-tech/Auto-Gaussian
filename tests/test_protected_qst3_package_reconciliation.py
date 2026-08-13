#!/usr/bin/env python3
"""Offline named-package closure regressions for protected QST3."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

from scripts import skill_package


ROOT = Path(__file__).parents[1]
SKILL = "auto-g16-rtwin-pbs"


def stage_package(root: Path) -> Path:
    installed = root / SKILL
    for target, source in skill_package.package_files_with_supplements(
        ROOT, SKILL
    ).items():
        destination = installed / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return installed.resolve()


OWNER_PROBE = """
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("qst3_packaged_lineage_probe", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
owners = module.owners()
print(json.dumps({
    "paths": {name: str(Path(owner.__file__).resolve()) for name, owner in owners.items()},
    "sha256": {name: hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest() for name, owner in owners.items()},
}, sort_keys=True))
"""


class ProtectedQST3PackageReconciliationTests(unittest.TestCase):
    def test_supplement_maps_only_repository_owned_qst3_closure(self) -> None:
        supplement = skill_package.load_json(
            ROOT
            / "config/deployment-package-supplements"
            / SKILL
            / "qst3-package-reconciliation.json"
        )
        self.assertEqual(supplement["schema"], skill_package.MANIFEST_SCHEMA)
        self.assertEqual(supplement["skill"], SKILL)
        sources = {item["source"] for item in supplement["include"]}
        self.assertIn("skills/auto-g16-ts-irc/scripts", sources)
        self.assertIn("skills/auto-g16-reaction-workflow/scripts", sources)
        self.assertIn("contracts/reaction-workflow", sources)
        self.assertTrue(PurePosixPath("/repository-owned/source").is_absolute())
        self.assertTrue(PureWindowsPath("C:/repository-owned/source").is_absolute())
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(PurePosixPath(source).is_absolute())
                self.assertFalse(PureWindowsPath(source).is_absolute())
        self.assertTrue(all(".codex/skills" not in source for source in sources))

        package = skill_package.package_files_with_supplements(ROOT, SKILL)
        self.assertEqual(
            package[Path("scripts/protected_qst3_adapter.py")],
            ROOT / "skills/auto-g16-rtwin-pbs/scripts/protected_qst3_adapter.py",
        )
        self.assertEqual(
            package[
                Path(
                    "dependencies/skills/auto-g16-ts-irc/scripts/ts_irc.py"
                )
            ],
            ROOT / "skills/auto-g16-ts-irc/scripts/ts_irc.py",
        )
        self.assertEqual(
            package[
                Path(
                    "dependencies/skills/auto-g16-reaction-workflow/scripts/"
                    "scientific_maturity_v2.py"
                )
            ],
            ROOT
            / "skills/auto-g16-reaction-workflow/scripts/scientific_maturity_v2.py",
        )
        self.assertNotIn(
            Path(
                "dependencies/skills/auto-g16-rtwin-pbs/scripts/gaussian_log.py"
            ),
            package,
        )

    def test_isolated_named_package_imports_exact_owners_without_effects(self) -> None:
        package = skill_package.package_files_with_supplements(ROOT, SKILL)
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / SKILL
            for target, source in package.items():
                destination = installed / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)

            probe = """
import importlib.util
import json
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location("qst3_packaged_probe", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
legacy, ts, maturity = module._owners()
status = module.production_effect_status()
print(json.dumps({
    "legacy": str(Path(legacy.__file__).resolve()),
    "ts": str(Path(ts.__file__).resolve()),
    "maturity": str(Path(maturity.__file__).resolve()),
    "status": status,
}, sort_keys=True))
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    probe,
                    str(installed / "scripts/protected_qst3_adapter.py"),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            installed_root = installed.resolve()
            dependency_root = (installed / "dependencies").resolve()
            self.assertTrue(payload["legacy"].startswith(str(installed_root)))
            self.assertTrue(payload["ts"].startswith(str(dependency_root)))
            self.assertTrue(
                payload["maturity"].startswith(str(dependency_root))
            )
            self.assertFalse(payload["status"]["production_submit_wired"])
            self.assertEqual(payload["status"]["qsub_calls"], 0)
            self.assertFalse(any(installed.rglob("__pycache__")))

    def test_repository_and_named_package_minimum_lineage_owners_are_exact(self) -> None:
        repository_source = (
            ROOT
            / "skills/auto-g16-reaction-workflow/scripts/"
            "scientific_closure_lineage.py"
        )
        repository_result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                OWNER_PROBE,
                str(repository_source),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(repository_result.returncode, 0, repository_result.stderr)
        repository = json.loads(repository_result.stdout)
        self.assertEqual(
            repository["paths"],
            {
                "approval": str(
                    (
                        ROOT
                        / "skills/auto-g16-rtwin-pbs/scripts/"
                        "gaussian_rtwin_pbs.py"
                    ).resolve()
                ),
                "input": str(
                    (
                        ROOT
                        / "skills/auto-g16-ts-irc/scripts/ts_irc.py"
                    ).resolve()
                ),
                "log": str(
                    (
                        ROOT
                        / "skills/auto-g16-rtwin-pbs/scripts/gaussian_log.py"
                    ).resolve()
                ),
            },
        )

        with tempfile.TemporaryDirectory() as temporary:
            installed = stage_package(Path(temporary))
            named_result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    OWNER_PROBE,
                    str(
                        installed
                        / "dependencies/skills/auto-g16-reaction-workflow/"
                        "scripts/scientific_closure_lineage.py"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(named_result.returncode, 0, named_result.stderr)
            named = json.loads(named_result.stdout)
            self.assertEqual(
                named["paths"],
                {
                    "approval": str(
                        (installed / "scripts/gaussian_rtwin_pbs.py").resolve()
                    ),
                    "input": str(
                        (
                            installed
                            / "dependencies/skills/auto-g16-ts-irc/"
                            "scripts/ts_irc.py"
                        ).resolve()
                    ),
                    "log": str(
                        (installed / "scripts/gaussian_log.py").resolve()
                    ),
                },
            )
            self.assertEqual(named["sha256"], repository["sha256"])
            self.assertFalse(any(installed.rglob("__pycache__")))

    def test_preloaded_gaussian_log_is_reused_only_when_exact(self) -> None:
        probe = """
import importlib.util
import sys
from pathlib import Path

installed = Path(sys.argv[1]).resolve()
case = sys.argv[2]
selected_log = installed / "scripts/gaussian_log.py"
preloaded_path = selected_log
if case == "different":
    preloaded_path = installed / "FAKE-INSTALLED/gaussian_log.py"
    preloaded_path.parent.mkdir()
    preloaded_path.write_bytes(
        selected_log.read_bytes()
        + b"\\n# distinct preloaded owner\\ndef _fake_log(*args, **kwargs):\\n"
          b"    return {'fake': True}\\nanalyze_log_file = _fake_log\\n"
          b"analyze_log_text = _fake_log\\nanalyze_workflow_log_file = _fake_log\\n"
    )
preloaded_spec = importlib.util.spec_from_file_location(
    "gaussian_log", preloaded_path
)
preloaded = importlib.util.module_from_spec(preloaded_spec)
sys.modules["gaussian_log"] = preloaded
preloaded_spec.loader.exec_module(preloaded)

source = (
    installed
    / "dependencies/skills/auto-g16-reaction-workflow/"
      "scripts/scientific_closure_lineage.py"
)
spec = importlib.util.spec_from_file_location(
    "qst3_preloaded_gaussian_log_probe", source
)
lineage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lineage)
if case == "different":
    try:
        lineage.owners()
    except lineage.LineageError as exc:
        print("DIFFERENT_PRELOAD_REJECTED: " + str(exc))
    else:
        raise AssertionError("DIFFERENT_PRELOADED_GAUSSIAN_LOG_ACCEPTED")
else:
    owners = lineage.owners()
    if (
        owners["log"] is not preloaded
        or owners["approval"].analyze_log_file
        is not preloaded.analyze_log_file
        or owners["approval"].analyze_log_text
        is not preloaded.analyze_log_text
        or owners["approval"].analyze_workflow_log_file
        is not preloaded.analyze_workflow_log_file
    ):
        raise AssertionError("EXACT_PRELOADED_GAUSSIAN_LOG_NOT_REUSED")
    print("EXACT_PRELOAD_REUSED")
"""
        with tempfile.TemporaryDirectory() as temporary:
            installed = stage_package(Path(temporary))
            for case, expected in (
                ("different", "DIFFERENT_PRELOAD_REJECTED:"),
                ("exact", "EXACT_PRELOAD_REUSED"),
            ):
                with self.subTest(case=case):
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            "-S",
                            "-B",
                            "-c",
                            probe,
                            str(installed),
                            case,
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(expected, result.stdout)
            self.assertFalse(any(installed.rglob("__pycache__")))

    def test_repository_and_named_package_minimum_lineage_receipt_roundtrips_in_fresh_processes(self) -> None:
        probe = """
import importlib.util
import sys
import tempfile
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
lineage_path = Path(sys.argv[2]).resolve()

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module

lineage = load(
    "qst3_isolated_roundtrip_lineage",
    lineage_path,
)
owners = lineage.owners()

sys.path.insert(0, str(repo))
from tests import test_protected_qst3_real_chain as real
from tests import test_scientific_maturity_v2 as maturity_support
sys.path.pop(0)
real.PBS = owners["approval"]
real.LINEAGE = lineage

with tempfile.TemporaryDirectory(prefix="qst3-packaged-lineage-data-") as temporary:
    root = Path(temporary).resolve()
    fixture = maturity_support.ScientificMaturityV2Tests(
        "test_positive_pilot_roundtrip_schemas_and_v1_compatibility"
    )
    fixture.setUp()
    _, _, review, mechanism = fixture.formal_base_context(root)
    minimum = review["minimum_records"][0]
    states = {item["state_id"]: item for item in mechanism["states"]}
    lineage_path = real.ProtectedQST3RealChainTests().minimum_lineage(
        root, minimum, states[minimum["state_id"]], source_kind="reviewed_result"
    )
    built = real.LINEAGE.validate_artifact(lineage_path)
    print(built["schema"] + " " + built["payload_sha256"])
"""
        with tempfile.TemporaryDirectory() as temporary:
            installed = stage_package(Path(temporary))
            lineage_paths = {
                "repository": (
                    ROOT
                    / "skills/auto-g16-reaction-workflow/scripts/"
                    "scientific_closure_lineage.py"
                ),
                "named-package": (
                    installed
                    / "dependencies/skills/auto-g16-reaction-workflow/"
                    "scripts/scientific_closure_lineage.py"
                ),
            }
            for layout, lineage_path in lineage_paths.items():
                with self.subTest(layout=layout):
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            "-S",
                            "-B",
                            "-c",
                            probe,
                            str(ROOT),
                            str(lineage_path),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    schema, payload = result.stdout.strip().split()
                    self.assertEqual(
                        schema, "gaussian-minimum-lineage-handoff/2"
                    )
                    self.assertRegex(payload, r"^[0-9a-f]{64}$")
            self.assertFalse(any(installed.rglob("__pycache__")))

    def test_named_package_owner_layouts_fail_closed_without_fallback(self) -> None:
        rejecting_probe = """
import importlib.util
import sys
from pathlib import Path

source = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("qst3_rejecting_lineage_probe", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    module.owners()
except module.LineageError as exc:
    print(type(exc).__name__ + ": " + str(exc))
else:
    raise AssertionError("HOSTILE_OWNER_LAYOUT_ACCEPTED")
"""
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary).resolve()
            base = stage_package(temporary_root / "base")
            for case in (
                "partial",
                "second-owner",
                "wrong-sha",
                "owner-symlink",
                "source-path-drift",
                "installed-fallback",
            ):
                with self.subTest(case=case):
                    case_root = temporary_root / case
                    installed = case_root / SKILL
                    shutil.copytree(base, installed)
                    source = (
                        installed
                        / "dependencies/skills/auto-g16-reaction-workflow/"
                        "scripts/scientific_closure_lineage.py"
                    )
                    if case in {"partial", "installed-fallback"}:
                        (installed / "scripts/gaussian_log.py").unlink()
                    elif case == "second-owner":
                        second = (
                            installed
                            / "dependencies/skills/auto-g16-rtwin-pbs/"
                            "scripts/gaussian_log.py"
                        )
                        second.parent.mkdir(parents=True)
                        shutil.copyfile(base / "scripts/gaussian_log.py", second)
                    elif case == "wrong-sha":
                        with (installed / "scripts/gaussian_log.py").open("ab") as handle:
                            handle.write(b"# reviewed owner byte drift\n")
                    elif case == "owner-symlink":
                        target = installed / "scripts/gaussian_log.py"
                        target.unlink()
                        target.symlink_to(base / "scripts/gaussian_log.py")
                    elif case == "source-path-drift":
                        source.unlink()
                        source.symlink_to(
                            base
                            / "dependencies/skills/auto-g16-reaction-workflow/"
                            "scripts/scientific_closure_lineage.py"
                        )

                    fake_home = case_root / "home"
                    fake_owner = (
                        fake_home
                        / ".codex/skills/auto-g16-rtwin-pbs/"
                        "scripts/gaussian_log.py"
                    )
                    fake_owner.parent.mkdir(parents=True)
                    shutil.copyfile(base / "scripts/gaussian_log.py", fake_owner)
                    effects = case_root / "effects"
                    effects.mkdir()
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            "-S",
                            "-B",
                            "-c",
                            rejecting_probe,
                            str(source),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env={
                            "HOME": str(fake_home),
                            "PATH": os.devnull,
                            "PYTHONPATH": str(fake_owner.parent),
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("LineageError:", result.stdout)
                    self.assertEqual(list(effects.iterdir()), [])
                    self.assertNotIn(str(fake_owner), result.stdout)
                    self.assertFalse(any(installed.rglob("__pycache__")))


if __name__ == "__main__":
    unittest.main()
