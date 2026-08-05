#!/usr/bin/env python3
"""Hostile offline tests for the trusted local Draft validation runner."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import py_compile
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "run_schema_validation.py"
SPEC = importlib.util.spec_from_file_location(
    "auto_g16_run_schema_validation_test", MODULE_PATH
)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class LocalSchemaValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.env = self.root / "schema-env"
        self.site_packages = (
            self.env
            / "lib"
            / f"python{RUNNER.TRUSTED_MINOR}"
            / "site-packages"
        )
        self.site_packages.mkdir(parents=True)
        self.pins = dict(RUNNER.AUDIT.SCHEMA_VALIDATION_PINS)
        self.validated: list[object] = []

    def tearDown(self) -> None:
        RUNNER.close_validated(self.validated)
        self.temporary.cleanup()

    def record_entry(self, path: Path) -> str:
        content = path.read_bytes()
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
        relative = path.relative_to(self.site_packages).as_posix()
        return f"{relative},sha256={digest},{len(content)}\n"

    def write_overlay(self, *, versions: dict[str, str] | None = None) -> None:
        selected = dict(self.pins)
        if versions:
            selected.update(versions)
        for distribution_name, import_name in RUNNER.DISTRIBUTION_IMPORTS.items():
            if import_name == "typing_extensions":
                module = self.site_packages / "typing_extensions.py"
            else:
                module = self.site_packages / import_name / "__init__.py"
            module.parent.mkdir(parents=True, exist_ok=True)
            module.write_text(
                f"PACKAGE_IDENTITY = {distribution_name!r}\n",
                encoding="utf-8",
            )
            normalized = distribution_name.replace("-", "_")
            info = self.site_packages / f"{normalized}-{selected[distribution_name]}.dist-info"
            info.mkdir()
            metadata = info / "METADATA"
            metadata.write_text(
                "Metadata-Version: 2.1\n"
                f"Name: {distribution_name}\n"
                f"Version: {selected[distribution_name]}\n",
                encoding="utf-8",
            )
            relative_record = (info / "RECORD").relative_to(self.site_packages).as_posix()
            (info / "RECORD").write_text(
                self.record_entry(module)
                + self.record_entry(metadata)
                + f"{relative_record},,\n",
                encoding="utf-8",
            )

    def candidate(self) -> object:
        return RUNNER._candidate_from_env(self.env, "test overlay")

    def add_console_script(
        self,
        *,
        name: str = "jsonschema",
        declared_name: str | None = None,
        record_path: str | None = None,
        content: bytes = b"#!/bin/sh\nexit 97\n",
        symlink: bool = False,
    ) -> tuple[Path, Path]:
        info = self.site_packages / f"jsonschema-{self.pins['jsonschema']}.dist-info"
        entry_points = info / "entry_points.txt"
        selected_name = name if declared_name is None else declared_name
        entry_points.write_text(
            f"[console_scripts]\n{selected_name} = jsonschema:PACKAGE_IDENTITY\n",
            encoding="utf-8",
        )
        script = self.env / "bin" / name
        script.parent.mkdir(exist_ok=True)
        if symlink:
            target = self.root / f"{name}-target"
            target.write_bytes(content)
            script.symlink_to(target)
        else:
            script.write_bytes(content)
            script.chmod(0o755)
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
        record = info / "RECORD"
        existing = record.read_text(encoding="utf-8")
        relative_entry_points = entry_points.relative_to(self.site_packages).as_posix()
        external = record_path or f"../../../bin/{name}"
        record.write_text(
            existing
            + self.record_entry(entry_points)
            + f"{external},sha256={digest},{len(content)}\n",
            encoding="utf-8",
        )
        return script, record

    def validate(self) -> object:
        item = RUNNER.validate_candidate(
            self.candidate(),
            self.pins,
            ["3.11", "3.12", "3.13"],
        )
        self.validated.append(item)
        return item

    @staticmethod
    def quiet_runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        kwargs["capture_output"] = True
        kwargs["text"] = True
        return subprocess.run(command, **kwargs)

    def test_environment_is_absolute_unique_and_needs_no_executable(self) -> None:
        with self.assertRaisesRegex(RUNNER.BlockedError, "absolute path"):
            RUNNER.discover_candidates(self.root, [Path("relative-env")], {})
        candidates = RUNNER.discover_candidates(self.root, [self.env], {})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].site_packages, self.site_packages)
        self.assertFalse((self.env / "bin" / "python").exists())

        extra = self.env / "lib" / "python3.10" / "site-packages"
        extra.mkdir(parents=True)
        with self.assertRaisesRegex(RUNNER.BlockedError, "exactly one"):
            RUNNER.discover_candidates(self.root, [self.env], {})

    def test_missing_environment_is_actionable_blocked_not_pass(self) -> None:
        with mock.patch.object(RUNNER, "_default_envs", return_value=()):
            with self.assertRaisesRegex(RUNNER.BlockedError, "never executes"):
                RUNNER.discover_candidates(self.root, [], {})

    @unittest.skipUnless(os.name == "posix", "POSIX permission hardening")
    def test_group_writable_or_symlinked_overlay_blocks(self) -> None:
        self.env.chmod(0o775)
        with self.assertRaisesRegex(RUNNER.BlockedError, "trusted user-owned"):
            RUNNER.discover_candidates(self.root, [self.env], {})
        self.env.chmod(0o755)

        outside = self.root / "outside-site"
        outside.mkdir()
        self.site_packages.rmdir()
        self.site_packages.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RUNNER.BlockedError, "exactly one"):
            RUNNER.discover_candidates(self.root, [self.env], {})

    def test_probe_uses_current_trusted_python_and_closes_origins(self) -> None:
        self.assertIn(
            'metadata.distributions(name=distribution_name, path=["."])',
            RUNNER.PROBE_SOURCE,
        )
        self.write_overlay()
        item = self.validate()
        self.assertEqual(item.payload["python_version"], RUNNER.TRUSTED_VERSION)
        self.assertEqual(item.payload["versions"], self.pins)
        self.assertEqual(set(item.payload["origins"]), set(self.pins))
        self.assertEqual(set(item.payload["distribution_file_counts"]), set(self.pins))
        self.assertTrue(all(count == 3 for count in item.payload["distribution_file_counts"].values()))
        self.assertEqual(item.payload["console_script_manifest"], {})

    def test_source_tamper_with_unchanged_metadata_version_and_record_blocks(self) -> None:
        self.write_overlay()
        module = self.site_packages / "jsonschema" / "__init__.py"
        module.write_text(
            "PACKAGE_IDENTITY = 'pre-probe forged source'\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RUNNER.BlockedError, "RECORD hash or size mismatch"):
            self.validate()

    def test_only_record_self_and_source_bound_pyc_may_be_unhashed(self) -> None:
        self.write_overlay()
        info = self.site_packages / f"jsonschema-{self.pins['jsonschema']}.dist-info"
        record = info / "RECORD"
        marker = self.root / "forged-pyc-executed"
        malicious = self.root / "malicious.py"
        malicious.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed')\n"
            "PACKAGE_IDENTITY = 'forged pyc'\n",
            encoding="utf-8",
        )
        pyc = self.site_packages / "jsonschema" / "__pycache__" / (
            "__init__." + sys.implementation.cache_tag + ".pyc"
        )
        pyc.parent.mkdir()
        py_compile.compile(
            str(malicious),
            cfile=str(pyc),
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )
        record.write_text(
            record.read_text(encoding="utf-8")
            + f"{pyc.relative_to(self.site_packages).as_posix()},,\n",
            encoding="utf-8",
        )
        self.validate()
        self.assertFalse(marker.exists(), "candidate pyc must never participate in import")

        unsupported = info / "UNHASHED"
        unsupported.write_text("untrusted\n", encoding="utf-8")
        record.write_text(
            record.read_text(encoding="utf-8")
            + f"{unsupported.relative_to(self.site_packages).as_posix()},,\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RUNNER.BlockedError, "unsupported unhashed RECORD"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

    def test_hashed_record_self_and_orphan_unhashed_pyc_block(self) -> None:
        self.write_overlay()
        info = self.site_packages / f"jsonschema-{self.pins['jsonschema']}.dist-info"
        record = info / "RECORD"
        original = record.read_text(encoding="utf-8")
        record_relative = record.relative_to(self.site_packages).as_posix()
        record.write_text(
            original.replace(
                f"{record_relative},,\n",
                f"{record_relative},sha256=AAAA,1\n",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RUNNER.BlockedError, "self-entry must be unhashed"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

        orphan = self.site_packages / "jsonschema" / "__pycache__" / (
            "orphan." + sys.implementation.cache_tag + ".pyc"
        )
        orphan.parent.mkdir(exist_ok=True)
        orphan.write_bytes(b"not importable")
        record.write_text(
            original + f"{orphan.relative_to(self.site_packages).as_posix()},,\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RUNNER.BlockedError, "without one hashed source"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

    def test_exact_declared_console_script_is_verified_but_never_executed(self) -> None:
        self.write_overlay()
        state = self.root / "console-script-executed"
        content = (
            "#!/bin/sh\n"
            f"touch {shlex.quote(str(state))}\n"
            "exit 0\n"
        ).encode("utf-8")
        self.add_console_script(content=content)
        item = self.validate()
        self.assertEqual(
            set(item.payload["console_script_manifest"]), {"jsonschema"}
        )
        passing = self.make_test_root(
            "import unittest\n"
            "class Sample(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertTrue(True)\n"
        )
        completion = RUNNER.run_inventory(
            item, passing, ["tests.test_sample"], runner=self.quiet_runner
        )
        self.assertTrue(completion["successful"])
        self.assertFalse(state.exists(), "console-script shell shim must never execute")

    def test_undeclared_and_noncanonical_console_script_escapes_block(self) -> None:
        self.write_overlay()
        self.add_console_script(name="evil", declared_name="jsonschema")
        with self.assertRaisesRegex(RUNNER.BlockedError, "undeclared console-script"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

        info = self.site_packages / f"jsonschema-{self.pins['jsonschema']}.dist-info"
        record = info / "RECORD"
        record.write_text(
            "\n".join(
                line
                for line in record.read_text(encoding="utf-8").splitlines()
                if "../../../bin/evil" not in line and "entry_points.txt" not in line
            )
            + "\n",
            encoding="utf-8",
        )
        _, record = self.add_console_script(
            name="jsonschema",
            record_path="../../../bin/../bin/jsonschema",
        )
        with self.assertRaisesRegex(RUNNER.BlockedError, "unsafe distribution-relative"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

    def test_console_script_symlink_record_hash_and_size_drift_block(self) -> None:
        self.write_overlay()
        script, record = self.add_console_script(symlink=True)
        with self.assertRaisesRegex(RUNNER.BlockedError, "Too many levels|origin/import"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

        script.unlink()
        script.write_bytes(b"#!/bin/sh\nexit 97\n")
        script.chmod(0o755)
        original = record.read_text(encoding="utf-8")
        record.write_text(original.replace("sha256=", "sha256=AAAA"), encoding="utf-8")
        with self.assertRaisesRegex(RUNNER.BlockedError, "hash or size mismatch"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )
        record.write_text(
            original.rsplit(",", 1)[0] + ",999999\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RUNNER.BlockedError, "hash or size mismatch"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

    def test_console_script_inode_replacement_after_probe_blocks(self) -> None:
        self.write_overlay()
        content = b"#!/bin/sh\nexit 97\n"
        script, _ = self.add_console_script(content=content)
        item = self.validate()
        script.unlink()
        script.write_bytes(content)
        script.chmod(0o755)
        with self.assertRaisesRegex(RUNNER.BlockedError, "no completion evidence"):
            RUNNER.run_inventory(
                item,
                self.root,
                ["tests.test_unreachable"],
                runner=self.quiet_runner,
            )

    def test_pin_drift_and_unsupported_current_minor_block(self) -> None:
        self.write_overlay(versions={"jsonschema": "4.25.1"})
        with self.assertRaisesRegex(RUNNER.BlockedError, "lock mismatch"):
            RUNNER.validate_candidate(
                self.candidate(),
                self.pins,
                ["3.11", "3.12", "3.13"],
            )
        with self.assertRaisesRegex(RUNNER.BlockedError, "outside the reviewed minor"):
            RUNNER.validate_candidate(
                self.candidate(),
                self.pins,
                ["3.10"],
            )

    def test_distribution_escape_and_import_symlink_block(self) -> None:
        self.write_overlay()
        info = self.site_packages / f"jsonschema-{self.pins['jsonschema']}.dist-info"
        record = info / "RECORD"
        record.write_text(
            "../outside.py,,\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            RUNNER.BlockedError, "origin/import|file inventory|counts disagree"
        ):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

        record.write_text(
            "jsonschema/__init__.py,,\n"
            f"{info.relative_to(self.site_packages).as_posix()}/METADATA,,\n"
            f"{info.relative_to(self.site_packages).as_posix()}/RECORD,,\n",
            encoding="utf-8",
        )
        module = self.site_packages / "jsonschema" / "__init__.py"
        outside = self.root / "outside.py"
        outside.write_text("FORGED = True\n", encoding="utf-8")
        module.unlink()
        module.symlink_to(outside)
        with self.assertRaisesRegex(RUNNER.BlockedError, "Too many levels|origin/import"):
            RUNNER.validate_candidate(
                self.candidate(), self.pins, ["3.11", "3.12", "3.13"]
            )

    def test_sitecustomize_and_caller_python_configuration_do_not_execute(self) -> None:
        self.write_overlay()
        marker = self.root / "sitecustomize-ran"
        (self.site_packages / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
            encoding="utf-8",
        )
        with mock.patch.dict(
            os.environ,
            {"PYTHONPATH": str(self.root / "shadow"), "PYTHONHOME": str(self.root)},
        ):
            self.validate()
        self.assertFalse(marker.exists())

    def test_path_replacement_after_probe_blocks_before_tests(self) -> None:
        self.write_overlay()
        item = self.validate()
        retired = self.site_packages.with_name("site-packages-retired")
        self.site_packages.rename(retired)
        self.site_packages.mkdir()
        with self.assertRaisesRegex(RUNNER.BlockedError, "path changed before tests"):
            RUNNER.run_inventory(item, self.root, ["tests.test_unreachable"])

    def test_platform_fchdir_dot_stays_bound_across_path_replacement(self) -> None:
        self.write_overlay()
        item = self.validate()
        retired = self.site_packages.with_name("site-packages-retired")
        self.site_packages.rename(retired)
        replacement = self.site_packages / "jsonschema"
        replacement.mkdir(parents=True)
        (replacement / "__init__.py").write_text(
            "PACKAGE_IDENTITY = 'forged replacement'\n", encoding="utf-8"
        )
        source = (
            "import os,sys\n"
            "os.fchdir(int(sys.argv[1]))\n"
            "sys.path.insert(0, '.')\n"
            "import jsonschema\n"
            "print(jsonschema.PACKAGE_IDENTITY)\n"
        )
        completed = subprocess.run(
            [str(RUNNER.TRUSTED_PYTHON), "-I", "-S", "-c", source, str(item.site_fd)],
            check=False,
            capture_output=True,
            text=True,
            pass_fds=(item.site_fd,),
            env={"PYTHONNOUSERSITE": "1"},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "jsonschema")

    def test_file_replacement_after_probe_blocks_without_completion(self) -> None:
        self.write_overlay()
        item = self.validate()
        module = self.site_packages / "jsonschema" / "__init__.py"
        module.write_text("FORGED_AFTER_PROBE = True\n", encoding="utf-8")
        with self.assertRaisesRegex(RUNNER.BlockedError, "no completion evidence"):
            RUNNER.run_inventory(
                item,
                self.root,
                ["tests.test_unreachable"],
                runner=self.quiet_runner,
            )

    def make_test_root(self, source: str) -> Path:
        test_root = self.root / "test-root"
        tests = test_root / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (tests / "test_sample.py").write_text(source, encoding="utf-8")
        return test_root

    def test_trusted_unittest_completion_distinguishes_pass_and_fail(self) -> None:
        self.write_overlay()
        item = self.validate()
        passing = self.make_test_root(
            "import unittest\n"
            "class Sample(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(2 + 2, 4)\n"
        )
        completion = RUNNER.run_inventory(
            item,
            passing,
            ["tests.test_sample"],
            runner=self.quiet_runner,
        )
        self.assertTrue(completion["successful"])
        self.assertEqual(completion["tests_run"], 1)

        (passing / "tests" / "test_sample.py").write_text(
            "import unittest\n"
            "class Sample(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.fail('synthetic failure')\n",
            encoding="utf-8",
        )
        completion = RUNNER.run_inventory(
            item,
            passing,
            ["tests.test_sample"],
            runner=self.quiet_runner,
        )
        self.assertFalse(completion["successful"])
        self.assertEqual(completion["failures"], 1)

    def test_missing_completion_evidence_is_blocked_not_pass(self) -> None:
        self.write_overlay()
        item = self.validate()

        def fake(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(Path(command[0]).resolve(), RUNNER.TRUSTED_PYTHON)
            self.assertNotIn(str(self.env / "bin" / "python"), command)
            return subprocess.CompletedProcess(command, 0)

        with self.assertRaisesRegex(RUNNER.BlockedError, "no completion evidence"):
            RUNNER.run_inventory(
                item,
                self.root,
                ["tests.test_forged"],
                runner=fake,
            )

        def disagreeing(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            pass_fds = kwargs["pass_fds"]
            self.assertIsInstance(pass_fds, tuple)
            evidence_fd = pass_fds[3]
            os.write(
                evidence_fd,
                json.dumps(
                    {
                        "schema": "auto-g16-schema-validation-test-completion/1",
                        "tests_run": 1,
                        "failures": 0,
                        "errors": 0,
                        "skipped": 0,
                        "successful": True,
                    }
                ).encode("utf-8"),
            )
            return subprocess.CompletedProcess(command, 1)

        with self.assertRaisesRegex(RUNNER.BlockedError, "exit status disagrees"):
            RUNNER.run_inventory(
                item,
                self.root,
                ["tests.test_forged"],
                runner=disagreeing,
            )

    def test_environment_variable_is_data_only_and_cli_takes_precedence(self) -> None:
        configured = self.root / "configured-env"
        configured_site = (
            configured
            / "lib"
            / f"python{RUNNER.TRUSTED_MINOR}"
            / "site-packages"
        )
        configured_site.mkdir(parents=True)
        candidates = RUNNER.discover_candidates(
            self.root,
            [self.env],
            {RUNNER.EXPLICIT_ENV: str(configured)},
        )
        self.assertEqual([item.environment for item in candidates], [self.env])
        candidates = RUNNER.discover_candidates(
            self.root,
            [],
            {RUNNER.EXPLICIT_ENV: str(configured)},
        )
        self.assertEqual([item.environment for item in candidates], [configured])

    def test_forged_candidate_python_cannot_attest_probe_or_test_success(self) -> None:
        python = self.env / "bin" / "python"
        python.parent.mkdir()
        state = self.root / "forged-state"
        forged = {
            "schema": "auto-g16-schema-validation-probe/1",
            "python_version": RUNNER.TRUSTED_VERSION,
            "versions": self.pins,
        }
        python.write_text(
            "#!/bin/sh\n"
            f"if [ ! -e {shlex.quote(str(state))} ]; then\n"
            f"  touch {shlex.quote(str(state))}\n"
            f"  printf '%s\\n' {shlex.quote(json.dumps(forged, sort_keys=True))}\n"
            "  exit 0\n"
            "fi\n"
            "printf '%s\\n' FORGED_TEST_SUCCESS\n"
            "exit 0\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--repo",
                str(ROOT),
                "--env",
                str(self.env),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={"PYTHONNOUSERSITE": "1"},
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("BLOCKED", result.stderr)
        self.assertNotIn("PASS", result.stdout + result.stderr)
        self.assertNotIn("FORGED_TEST_SUCCESS", result.stdout + result.stderr)
        self.assertFalse(state.exists(), "environment-local executable must never run")

    def test_python_option_is_removed(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--python", "/forged/bin/python"],
            check=False,
            capture_output=True,
            text=True,
            env={"PYTHONNOUSERSITE": "1"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)
        self.assertNotIn("PASS", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
