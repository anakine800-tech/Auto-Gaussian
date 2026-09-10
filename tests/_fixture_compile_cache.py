"""Cache only immutable backend CodeTypes during one synthetic fixture setup.

Production sources, builtins.compile, source reads, module namespaces, and all
single-use authorities remain unchanged. Nothing is cached across fixtures.
"""
from __future__ import annotations

import __future__
import builtins
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from importlib.machinery import SourceFileLoader
from operator import index
from pathlib import Path
import sys
import threading
from types import BuiltinFunctionType, CodeType


_ROOT = Path(__file__).resolve().parents[1]
_WRAPPER_PATH = str(_ROOT / "skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py")
_BACKEND_PATH = str(_ROOT / "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py")
_ORIGINAL_COMPILE = builtins.compile
_ORIGINAL_EXEC_MODULE = SourceFileLoader.exec_module
_SCOPE_LOCK = threading.Lock()
_MISSING = object()
_FUTURE_MASK = sum(getattr(__future__, name).compiler_flag for name in __future__.all_feature_names)
_MAX_CACHE_ENTRIES = 8
_MAX_SOURCE_BYTES = 1024 * 1024


@dataclass
class _CacheStats:
    enabled: bool = False
    hits: int = 0
    misses: int = 0
    intercepted_modules: int = 0


@contextmanager
def fixture_compilation_cache():
    """Optimize the exact wrapper in the calling thread until setup returns."""
    stats = _CacheStats()
    if (type(_ORIGINAL_COMPILE) is not BuiltinFunctionType
            or builtins.compile is not _ORIGINAL_COMPILE
            or SourceFileLoader.exec_module is not _ORIGINAL_EXEC_MODULE
            or not _SCOPE_LOCK.acquire(blocking=False)):
        yield stats
        return
    owner_thread = threading.get_ident()
    wrapper_path, backend_path = _WRAPPER_PATH, _BACKEND_PATH
    cache = OrderedDict()
    stats.enabled = True

    def compile_for(namespace):
        def cached_compile(source, filename, mode, flags=0, dont_inherit=False,
                           optimize=-1, *, _feature_version=-1):
            try:
                flags = index(flags)
                dont_inherit = bool(dont_inherit)
                caller = sys._getframe(1)
                try:
                    inherited = caller.f_code.co_flags & _FUTURE_MASK if not dont_inherit else 0
                    eligible_caller = (caller.f_globals is namespace
                                       and caller.f_code.co_filename == wrapper_path)
                finally:
                    del caller
                effective_flags = flags | inherited
                compiler = builtins.compile
                eligible = (compiler is _ORIGINAL_COMPILE
                            and threading.get_ident() == owner_thread
                            and eligible_caller
                            and type(source) is bytes and len(source) <= _MAX_SOURCE_BYTES
                            and type(filename) is str and filename == backend_path
                            and type(mode) is str and mode == "exec"
                            and type(flags) is int and type(dont_inherit) in (bool, int)
                            and type(optimize) is int and type(_feature_version) is int)
                # Explicit flags prevent this helper's own future flags leaking in.
                arguments = dict(flags=effective_flags, dont_inherit=True,
                                 optimize=optimize, _feature_version=_feature_version)
                if not eligible:
                    return compiler(source, filename, mode, **arguments)
                key = (source, filename, mode, flags, bool(dont_inherit), effective_flags,
                       optimize, sys.flags.optimize if optimize == -1 else optimize,
                       _feature_version, sys.implementation.cache_tag, sys.version_info[:3])
                code = cache.get(key, _MISSING)
                if code is not _MISSING:
                    stats.hits += 1
                    cache.move_to_end(key)
                    return code
                code = compiler(source, filename, mode, **arguments)
                if type(code) is CodeType:
                    stats.misses += 1
                    cache[key] = code
                    if len(cache) > _MAX_CACHE_ENTRIES:
                        cache.popitem(last=False)
                return code
            finally:
                # Remove the injected name before the backend executes, so even
                # backend code which captures compile sees the real builtin.
                if namespace.get("compile") is cached_compile:
                    namespace.pop("compile")
        return cached_compile

    def execute_module(loader, module):
        namespace = vars(module)
        if (threading.get_ident() != owner_thread
                or type(loader) is not SourceFileLoader
                or loader.path != wrapper_path
                or namespace.get("__file__") != wrapper_path
                or "compile" in namespace
                or "__builtins__" in namespace):
            return _ORIGINAL_EXEC_MODULE(loader, module)
        stats.intercepted_modules += 1
        compiler = compile_for(namespace)
        namespace["compile"] = compiler
        try:
            return _ORIGINAL_EXEC_MODULE(loader, module)
        finally:
            # The wrapper/backend never persist a compiler or namespace cache.
            if namespace.get("compile") is compiler:
                namespace.pop("compile")

    try:
        SourceFileLoader.exec_module = execute_module
        yield stats
    finally:
        SourceFileLoader.exec_module = _ORIGINAL_EXEC_MODULE
        cache.clear()
        _SCOPE_LOCK.release()


def cache_fixture_preparation(function):
    @wraps(function)
    def prepare(*args, **kwargs):
        with fixture_compilation_cache():
            return function(*args, **kwargs)
    return prepare
