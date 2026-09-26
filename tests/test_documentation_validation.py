"""Documentation scope, real Git identity and chemistry CI boundary regressions."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import check_documentation as docs
from scripts import select_validation as selector


ROOT = Path(__file__).resolve().parents[1]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root: Path, path: str, text: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(root, "add", "--", path)
    git(root, "commit", "-qm", "offline fixture")
    return git(root, "rev-parse", "HEAD")


def fixture(root: Path) -> str:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Documentation Test")
    git(root, "config", "user.email", "documentation@example.invalid")
    commit(root, ".gitignore", "__pycache__/\n")
    for relative in ("scripts/check_documentation.py", "scripts/select_validation.py",
                     "config/validation-selection.json"):
        commit(root, relative, (ROOT / relative).read_text(encoding="utf-8"))
    return commit(root, "README.md", "# Auto-G16 introduction\n")


class DocumentationValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = selector._load_manifest_for_test(ROOT / selector.MANIFEST_RELATIVE)

    def select(self, *paths: str, status: str = "M") -> dict:
        return selector.select_changes(self.manifest, [
            {"status": status, "paths": [path]} for path in paths
        ])

    def test_exact_reviewed_list_has_real_nonempty_checks(self) -> None:
        self.assertEqual(docs.DOCUMENTS, {
            "README.md", "docs/v3/INDEX.md", "docs/documentation-guide.md",
        })
        for path in docs.DOCUMENTS:
            with self.subTest(path=path):
                result = self.select(path)
                self.assertTrue(docs.is_lightweight(result))
                self.assertEqual(set(result["tests"]), {
                    "tests.test_release_hygiene", "tests.test_documentation_validation",
                })
        self.assertTrue(docs.is_lightweight(self.select(*sorted(docs.DOCUMENTS))))

    def test_all_other_existing_v3_documents_keep_conservative_ownership(self) -> None:
        for path in (ROOT / "docs/v3").rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative in docs.DOCUMENTS:
                continue
            with self.subTest(path=relative):
                selected = self.select(relative)
                self.assertEqual(selected["lane"], "v3-full")
                self.assertEqual(selected["tests"], self.manifest["v3_full_tests"])
                self.assertFalse(docs.is_lightweight(selected))

    def test_mixed_authority_control_code_and_dependencies_never_waive_chemistry(self) -> None:
        for path in ("AGENTS.md", "OWNER_DECISIONS.md", "docs/development-handbook.md",
                     "docs/v3/acceptance.md", "docs/v3/post-core-history.md",
                     "docs/v3/publisher-r4/README.md", "auto_g16/core/models.py",
                     "auto_g16/core/store.py", "auto_g16/transport/_driver.py",
                     "auto_g16/transport/program.py",
                     "requirements/chemistry.lock.txt", "requirements/schema-validation.lock.txt",
                     ".github/workflows/offline-tests.yml", *self.manifest["self_protecting_paths"]):
            with self.subTest(path=path):
                alone = self.select(path)
                mixed = self.select("docs/v3/INDEX.md", path)
                self.assertEqual(mixed["lane"], alone["lane"])
                self.assertTrue(set(alone["tests"]) <= set(mixed["tests"]))
                self.assertEqual(alone["safety_evidence"], mixed["safety_evidence"])
                self.assertFalse(docs.is_lightweight(mixed))

    def test_unknown_paths_and_empty_selection_do_not_waive_chemistry(self) -> None:
        for path in ("docs/v3/new.md", "docs/history/new.md", "misc.md"):
            selected = self.select(path)
            self.assertEqual(selected["lane"], "legacy-release")
            self.assertTrue(selected["fail_closed"])
            self.assertFalse(docs.is_lightweight(selected))
        self.assertFalse(docs.is_lightweight(self.select()))
        with self.assertRaisesRegex(selector.SelectionError, "UNMAPPED_MODERN_PATH"):
            self.select("README.md", "auto_g16/new/unknown.py")
        with self.assertRaisesRegex(selector.SelectionError, "UNMAPPED_MODERN_PATH"):
            self.select("auto_g16/transport/driver.py")
        with self.assertRaisesRegex(selector.SelectionError, "UNMAPPED_MODERN_PATH"):
            self.select("README.md", "auto_g16/transport/driver.py")

    def test_add_delete_copy_and_rename_cannot_launder_contract_paths(self) -> None:
        for status in ("A", "D", "T"):
            self.assertFalse(docs.is_lightweight(self.select("README.md", status=status)))
        for status in ("R100", "C100"):
            for source in ("README.md", "docs/v3/acceptance.md", "docs/v3/post-core-history.md"):
                selected = selector.select_changes(self.manifest, [
                    {"status": status, "paths": [source, "docs/v3/INDEX.md"]},
                ])
                self.assertFalse(docs.is_lightweight(selected))
                if source != "README.md":
                    self.assertEqual(selected["lane"], "v3-full")

    def test_actual_reviewed_documents_and_local_links(self) -> None:
        docs.check_documents(ROOT, sorted(docs.DOCUMENTS))

    def test_checker_rejects_missing_empty_invalid_and_escaping_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for text in ("", "# Auto-G16\n\0", "wrong title",
                         "# Auto-G16\n[missing](missing.md)",
                         "# Auto-G16\n[escape](../outside.md)"):
                (root / "README.md").write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    docs.check_documents(root, ["README.md"])
            (root / "README.md").write_bytes(b"\xff")
            with self.assertRaises(UnicodeError):
                docs.check_documents(root, ["README.md"])
            with self.assertRaises(ValueError):
                docs.check_documents(root, ["unreviewed.md"])

    def test_checker_rejects_symlink_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "target").write_text("# Auto-G16\n")
            (root / "README.md").symlink_to(root / "target")
            with self.assertRaises(ValueError):
                docs.check_documents(root, ["README.md"])

    def test_real_git_recomputation_accepts_only_exact_clean_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = fixture(root)
            head = commit(root, "README.md", "# Auto-G16 updated introduction\n")
            self.assertFalse(docs.chemistry_required(root, base, head))
            with self.assertRaises(selector.SelectionError):
                docs.chemistry_required(root, "not-a-sha", head)
            with self.assertRaises(selector.SelectionError):
                docs.chemistry_required(root, base, base)
            (root / "README.md").write_text("dirty\n")
            with self.assertRaises(selector.SelectionError):
                docs.chemistry_required(root, base, head)

    def test_real_cli_emits_no_success_output_for_invalid_identity_or_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = fixture(root)
            head = commit(root, "README.md", "# Auto-G16\n[missing](missing.md)\n")
            for requested in (head, "invalid"):
                result = subprocess.run([sys.executable, str(root / "scripts/check_documentation.py"),
                                         "--base", base, "--head", requested],
                                        cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_real_cli_code_mix_requires_chemistry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = fixture(root)
            commit(root, "README.md", "# Auto-G16 updated\n")
            head = commit(root, "auto_g16/core/models.py", "VALUE = 1\n")
            result = subprocess.run([sys.executable, str(root / "scripts/check_documentation.py"),
                                     "--base", base, "--head", head],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "chemistry-required=true\n")

    def test_ci_gates_only_optional_work_and_always_runs_scope_and_dependency_audit(self) -> None:
        # A later workflow-only edit must actually execute these guard checks.
        selected = self.select(".github/workflows/offline-tests.yml")
        self.assertEqual(selected["lane"], "affected")
        self.assertIn("tests.test_documentation_validation", selected["tests"])
        workflow = (ROOT / ".github/workflows/offline-tests.yml").read_text()
        chemistry = workflow.split("  chemistry-dependencies:\n", 1)[1]
        self.assertIn("if: needs.source-archive-release.result == 'success'", chemistry)
        steps = chemistry.split("      - name: ")[1:]
        by_name = {step.splitlines()[0]: step for step in steps}
        for name in ("Verify exact documentation scope", "Audit chemistry dependency declarations"):
            self.assertNotIn("        if:", by_name[name])
        scope = by_name["Verify exact documentation scope"]
        self.assertIn("needs.source-archive-release.outputs.validation-base", scope)
        self.assertIn("needs.source-archive-release.outputs.validation-head", scope)
        self.assertIn('python scripts/check_documentation.py --base "$VALIDATION_BASE" --head "$VALIDATION_HEAD" >> "$GITHUB_OUTPUT"', scope)
        for name, step in by_name.items():
            if name not in {"Verify exact documentation scope", "Audit chemistry dependency declarations",
                            "Run all required Draft 2020-12 contract Schemas"}:
                self.assertIn("if: steps.documentation-scope.outputs.chemistry-required != 'false'", step)
        schema = by_name["Run all required Draft 2020-12 contract Schemas"]
        self.assertIn("outputs.validation-lane == 'v3-full'", schema)
        self.assertIn("outputs.validation-lane == 'legacy-release'", schema)
        self.assertNotIn("continue-on-error", workflow)

    def test_goodvibes_differential_runs_once_inside_complete_thermochemistry(self) -> None:
        from tests.v31 import thermochemistry

        def identifiers(suite):
            return [name for item in suite for name in
                    (identifiers(item) if isinstance(item, unittest.TestSuite) else [item.id()])]

        complete = identifiers(unittest.defaultTestLoader.loadTestsFromModule(thermochemistry))
        qualification = identifiers(unittest.defaultTestLoader.loadTestsFromName(
            "tests.v31.thermochemistry.test_goodvibes_qualification"))
        self.assertTrue(qualification)
        for name in qualification:
            self.assertEqual(complete.count(name), 1)
        workflow = (ROOT / ".github/workflows/offline-tests.yml").read_text()
        self.assertEqual(workflow.count('run_suite("tests.v31.thermochemistry")'), 1)
        self.assertNotIn('run_suite("tests.v31.thermochemistry.test_goodvibes_qualification")', workflow)
        self.assertIn('if len(errors) != 14 or maximum > 1e-12:', workflow)
        self.assertIn('not result.wasSuccessful() or result.skipped or result.testsRun == 0', workflow)


if __name__ == "__main__":
    unittest.main()
