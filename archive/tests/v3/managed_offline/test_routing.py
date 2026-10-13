import ast
import json
from pathlib import Path
import unittest

from scripts import select_validation as selector
from scripts.static_quality import inspect_source, SUPPORTED_RULES

ROOT = Path(__file__).resolve().parents[3]
MODULES = ("tests.v3.managed_offline.test_material", "tests.v3.managed_offline.test_review",
           "tests.v3.managed_offline.test_lifecycle", "tests.v3.managed_offline.test_routing")


class RoutingTests(unittest.TestCase):
    def test_every_prototype_path_has_route_and_selected_modules_contain_tests(self):
        manifest = selector.validate_manifest(json.loads((ROOT / "config/validation-selection.json").read_text()))
        paths = [str(p.relative_to(ROOT)) for folder in ("auto_g16/_managed_offline", "tests/v3/managed_offline") for p in (ROOT / folder).glob("*.py")]
        selector.validate_modern_ownership(manifest, paths)
        result = selector.select_changes(manifest, [{"status": "M", "paths": [p]} for p in paths])
        self.assertEqual(result["lane"], "affected")
        self.assertEqual(result["matched_routes"], ["mac-direct-managed-offline-v1"])
        self.assertFalse(result["fail_closed"])
        self.assertTrue(set(MODULES) <= set(result["tests"]))
        for module in MODULES:
            suite = unittest.TestLoader().loadTestsFromName(module)
            self.assertGreater(suite.countTestCases(), 0)
            self.assertNotIn("_FailedTest", str(suite))

    def test_contract_keeps_conservative_doc_route_and_manifest_self_protection(self):
        manifest = selector.validate_manifest(json.loads((ROOT / "config/validation-selection.json").read_text()))
        result = selector.select_changes(manifest, [{"status": "A", "paths": ["docs/v3/contracts/mac-direct-managed-offline-v1.md"]}])
        self.assertEqual(result["lane"], "v3-full")
        self.assertEqual(result["tests"], manifest["v3_full_tests"])
        result = selector.select_changes(manifest, [{"status": "M", "paths": ["config/validation-selection.json"]}])
        self.assertEqual(result["lane"], "legacy-release")
        self.assertTrue(result["fail_closed"])

    def test_private_model_has_no_process_network_or_production_import_seam(self):
        for path in (ROOT / "auto_g16/_managed_offline").glob("*.py"):
            source = path.read_text()
            self.assertEqual(inspect_source(source, str(path), SUPPORTED_RULES), [])
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({a.name for a in node.names} & {"socket", "subprocess", "ctypes"})
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith("auto_g16.transport"))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, {"Popen", "system", "fork", "execv", "execve", "spawn", "connect"})

    def test_contract_is_named_nonproduction_and_retains_final_crest_scope(self):
        source = (ROOT / "docs/v3/contracts/mac-direct-managed-offline-v1.md").read_text()
        for text in ("non-production", "final CREST objective", "F_FULLFSYNC", "independent L3", "No commit"):
            self.assertIn(text, source)
