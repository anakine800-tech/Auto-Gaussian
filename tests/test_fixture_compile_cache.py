"""Narrow synthetic fidelity tests for the fixture-only compiler cache."""
from __future__ import annotations

import builtins
from concurrent.futures import ThreadPoolExecutor
from importlib.machinery import SourceFileLoader
import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from tests import _fixture_compile_cache as cache


class FixtureCompilationCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.wrapper = self.root / "wrapper.py"
        self.backend = self.root / "backend.py"
        self.original_compile = builtins.compile
        self.original_loader = SourceFileLoader.exec_module
        bytecode = patch.object(sys, "dont_write_bytecode", True)
        bytecode.start()
        self.addCleanup(bytecode.stop)
        self.wrapper_source()
        self.backend.write_text("token = object()\ndef value(): return token\nsaved_compile = compile\n")
        for name, value in (("_WRAPPER_PATH", str(self.wrapper)), ("_BACKEND_PATH", str(self.backend))):
            item = patch.object(cache, name, value)
            item.start()
            self.addCleanup(item.stop)

    def wrapper_source(self, prefix="", arguments=""):
        self.wrapper.write_text(prefix + "from pathlib import Path\n"
            "backend = Path(__file__).with_name('backend.py')\n"
            "exec(compile(backend.read_bytes(), str(backend), 'exec'" + arguments + "), globals())\n")

    def load(self, name="synthetic_wrapper", explicit_compile=None, path=None):
        spec = importlib.util.spec_from_file_location(name, self.wrapper if path is None else path)
        module = importlib.util.module_from_spec(spec)
        if explicit_compile is not None:
            module.compile = explicit_compile
        spec.loader.exec_module(module)
        return module

    def tearDown(self):
        self.assertIs(builtins.compile, self.original_compile)
        self.assertIs(SourceFileLoader.exec_module, self.original_loader)

    def test_fresh_modules_functions_tokens_and_original_builtins_after_hits(self):
        with cache.fixture_compilation_cache() as stats:
            first, second = self.load("first"), self.load("second")
            self.assertIs(builtins.compile, self.original_compile)
            self.assertEqual((stats.misses, stats.hits), (1, 1))
            self.assertIsNot(first, second)
            self.assertIsNot(first.value, second.value)
            self.assertIsNot(first.token, second.token)
            self.assertIs(first.value.__code__, second.value.__code__)
            for module in (first, second):
                self.assertIs(module.saved_compile, self.original_compile)
                self.assertNotIn("compile", vars(module))
                self.assertIs(module.value.__globals__, vars(module))
        self.assertIs(first.value(), first.token)
        self.assertIs(second.value(), second.token)
        with cache.fixture_compilation_cache() as next_stats:
            self.load()
            self.assertEqual((next_stats.misses, next_stats.hits), (1, 0))

    def test_original_source_is_read_on_each_load_and_changed_bytes_miss(self):
        original_read = Path.read_bytes
        reads = []
        def read(path):
            if path == self.backend:
                reads.append(original_read(path))
            return original_read(path)
        with patch.object(Path, "read_bytes", read), cache.fixture_compilation_cache() as stats:
            self.load()
            self.backend.write_text("token = object()\ndef value(): return 'changed'\n")
            changed = self.load()
            self.assertEqual(changed.value(), "changed")
            self.assertEqual((stats.misses, stats.hits), (2, 0))
        self.assertEqual(len(reads), 2)
        self.assertNotEqual(reads[0], reads[1])

    def test_nested_fixture_preparation_uses_outer_cache_and_restores_loader(self):
        @cache.cache_fixture_preparation
        def prepare():
            self.load("nested_first")
            self.load("nested_second")
        with cache.fixture_compilation_cache() as stats:
            with cache.fixture_compilation_cache() as nested:
                self.assertFalse(nested.enabled)
            prepare()
            self.assertEqual((stats.misses, stats.hits), (1, 1))
            self.assertEqual(stats.intercepted_modules, 2)
            self.assertIs(builtins.compile, self.original_compile)
        self.assertIs(SourceFileLoader.exec_module, self.original_loader)

    def test_future_inheritance_and_explicit_dont_inherit_are_preserved(self):
        self.backend.write_text("def value(item: UndefinedName): return item\n")
        with cache.fixture_compilation_cache() as stats:
            with self.assertRaises(NameError):
                self.load()
            self.wrapper_source("from __future__ import annotations\n")
            module = self.load()
            self.assertEqual(module.value.__annotations__, {"item": "UndefinedName"})
            self.wrapper_source("from __future__ import annotations\n", ", dont_inherit=True")
            with self.assertRaises(NameError):
                self.load()
            self.assertEqual(stats.misses, 3)
            self.assertEqual(stats.hits, 0)

    def test_optimization_flag_changes_cache_key_and_assertion_behavior(self):
        self.backend.write_text("def value():\n    assert False\n    return 7\n")
        with cache.fixture_compilation_cache() as stats:
            self.wrapper_source(arguments=", optimize=0")
            original = self.load()
            with self.assertRaises(AssertionError):
                original.value()
            self.wrapper_source(arguments=", optimize=1, dont_inherit=True")
            optimized = self.load()
            self.assertEqual(optimized.value(), 7)
            self.assertEqual((stats.misses, stats.hits), (2, 0))

    def test_indexable_and_invalid_flags_match_uncached_compile(self):
        self.backend.write_text("def value(item: UndefinedName): return item\n")
        for expression in ("type('IndexFlags', (), {'__index__': lambda self: 0})()",
                           "1.5", "'0'", "-1", "1 << 100"):
            with self.subTest(flags=expression):
                self.wrapper_source("from __future__ import annotations\n",
                                    ", flags=" + expression)
                def outcome():
                    try:
                        return ("accepted", self.load().value.__annotations__)
                    except Exception as exc:
                        return (type(exc), str(exc))
                original = outcome()
                with cache.fixture_compilation_cache():
                    self.assertEqual(outcome(), original)

    def test_dont_inherit_truthiness_matches_uncached_compile(self):
        self.backend.write_text("def value(item: UndefinedName): return item\n")
        for expression in ("type('IndexInherit', (), {'__index__': lambda self: 0})()",
                           "type('IndexInherit', (), {'__index__': lambda self: 1})()",
                           "1.5", "'0'"):
            with self.subTest(dont_inherit=expression):
                self.wrapper_source("from __future__ import annotations\n",
                                    ", dont_inherit=" + expression)
                def outcome():
                    try:
                        return ("accepted", self.load().value.__annotations__)
                    except Exception as exc:
                        return (type(exc), str(exc))
                original = outcome()
                with cache.fixture_compilation_cache():
                    self.assertEqual(outcome(), original)

    def test_mode_subclass_cannot_alias_an_exec_cache_entry(self):
        with cache.fixture_compilation_cache() as stats:
            self.load()
            self.wrapper_source(
                "class Mode(str):\n"
                "    def __eq__(self, other): return other == 'exec'\n"
                "    def __hash__(self): return hash('exec')\n")
            self.wrapper.write_text(self.wrapper.read_text().replace(
                "str(backend), 'exec'", "str(backend), Mode('eval')"))
            with self.assertRaises(SyntaxError):
                self.load()
            self.assertEqual((stats.hits, stats.misses), (0, 1))
        with self.assertRaises(SyntaxError):
            self.load()

    def test_compile_spy_before_scope_disables_cache_and_body_spy_is_visible(self):
        with patch.object(builtins, "compile", wraps=self.original_compile) as spy:
            with cache.fixture_compilation_cache() as stats:
                self.load()
                self.assertFalse(stats.enabled)
            self.assertTrue(spy.called)
        with cache.fixture_compilation_cache():
            self.load()
        with patch.object(builtins, "compile", wraps=self.original_compile) as body_spy:
            self.load()
            self.assertTrue(body_spy.called)

    def test_explicit_global_compiler_is_preserved_without_interception(self):
        with patch.object(builtins, "compile", wraps=self.original_compile) as spy:
            explicit = spy
        with cache.fixture_compilation_cache() as stats:
            module = self.load(explicit_compile=explicit)
            self.assertIs(module.compile, explicit)
            self.assertIs(module.saved_compile, explicit)
            self.assertEqual((stats.intercepted_modules, stats.misses, stats.hits), (0, 0, 0))
            self.assertTrue(explicit.called)

    def test_preinstalled_module_builtins_compiler_is_not_bypassed(self):
        def deny(*args, **kwargs):
            raise RuntimeError("custom module compiler denied")
        def load_custom():
            spec = importlib.util.spec_from_file_location("custom_builtins", self.wrapper)
            module = importlib.util.module_from_spec(spec)
            module.__builtins__ = {**vars(builtins), "compile": deny}
            spec.loader.exec_module(module)
        with self.assertRaisesRegex(RuntimeError, "custom module compiler denied"):
            load_custom()
        with cache.fixture_compilation_cache() as stats:
            with self.assertRaisesRegex(RuntimeError, "custom module compiler denied"):
                load_custom()
            self.assertEqual((stats.intercepted_modules, stats.hits, stats.misses), (0, 0, 0))

    def test_other_threads_and_other_paths_use_original_loader(self):
        other = self.root / "other.py"
        other.write_bytes(self.wrapper.read_bytes())
        with cache.fixture_compilation_cache() as stats:
            with ThreadPoolExecutor(max_workers=1) as pool:
                child = pool.submit(self.load).result()
            external = self.load(path=other)
            self.assertEqual(stats.intercepted_modules, 0)
            self.assertEqual((stats.hits, stats.misses), (0, 0))
            self.assertIs(child.saved_compile, self.original_compile)
            self.assertIs(external.saved_compile, self.original_compile)
            self.load()
            self.assertEqual(stats.misses, 1)

    def test_exception_restores_loader_and_module_global_before_backend_execution(self):
        self.backend.write_text("assert 'compile' not in globals()\nraise RuntimeError('synthetic failure')\n")
        spec = importlib.util.spec_from_file_location("failing", self.wrapper)
        module = importlib.util.module_from_spec(spec)
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with cache.fixture_compilation_cache():
                spec.loader.exec_module(module)
        self.assertNotIn("compile", vars(module))
        self.assertIs(SourceFileLoader.exec_module, self.original_loader)
        self.assertIs(builtins.compile, self.original_compile)

    def test_backend_defined_compiler_name_is_not_removed(self):
        self.backend.write_text("compile = 'source-owned-value'\n")
        with cache.fixture_compilation_cache():
            module = self.load()
        self.assertEqual(module.compile, "source-owned-value")


class SealedFixtureCompilationCacheTests(unittest.TestCase):
    def test_restored_compiler_preserves_currentness_and_one_use_authority(self):
        from tests.test_direct_trusted_session_composition import PortableSessionFixture, SESSION, W5
        compiler, loader = builtins.compile, SourceFileLoader.exec_module
        with tempfile.TemporaryDirectory(prefix="auto-g16-cached-sealed-fixture-") as temporary:
            fixture = PortableSessionFixture(Path(temporary).resolve())
            try:
                self.assertIs(builtins.compile, compiler)
                self.assertIs(SourceFileLoader.exec_module, loader)
                capability = fixture.compose()
                capability.assert_current()
                lease = capability.consume_for_w5_once()
                lease.assert_current()
                seam = SESSION.consume_w5_operation_seam_once(lease)
                result = W5._consume_with_test_driver_once(
                    seam, W5._test_driver(stdout=b"731.master\n"),
                    _test_token=W5._TEST_DRIVER_TOKEN,
                )
                self.assertEqual(result.portable_projection()["qsub"]["job_id"], "731.master")
                with self.assertRaises(SESSION.DirectTrustedSessionError):
                    capability.consume_for_w5_once()
                with self.assertRaises(SESSION.DirectTrustedSessionError):
                    SESSION.consume_w5_operation_seam_once(lease)
            finally:
                fixture.close()


if __name__ == "__main__":
    unittest.main()
