"""Shared pytest hooks; child Python bootstrap has no pytest dependency."""
import functools
from pathlib import Path
import sys
import tempfile
from _test_home_isolation import TestHomeSession

import atexit
import pytest

_session = None


def start_session(repo):
    global _session
    if _session is None or _session.closed:
        _session = TestHomeSession(repo)
        atexit.register(_session.close)
        sys.path.insert(0, str(repo / 'ag/src'))
        # Python code filenames such as <frozen genericpath> have no disk source.
        # Stop pytest before inspect/stat; do not relax the filesystem guard or
        # catch the original HomeAccessError while formatting its traceback.
        from _pytest._code.code import Code
        for name in ('path', 'fullsource'):
            original = getattr(Code, name)

            @functools.wraps(original.fget)
            def source(code, _get=original.fget, _name=name):
                filename = code.raw.co_filename
                if filename.startswith('<') and filename.endswith('>'):
                    return filename if _name == 'path' else None
                return _get(code)

            _session.guard.patch(Code, name, property(source))


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    config.inicfg['cache_dir'] = str(_session.root / 'pytest-cache')
    config._inicache.pop('cache_dir', None)


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path, config):
    # Apply pytest's existing exclusions before its virtualenv metadata probes.
    # This changes no test selection and grants no access to ignored directories.
    import fnmatch
    if collection_path.name == '__pycache__' or any(
        fnmatch.fnmatch(str(collection_path), pattern) or fnmatch.fnmatch(collection_path.name, pattern)
        for pattern in config.getini('norecursedirs')
    ):
        return True
    return None


@pytest.fixture(autouse=True)
def isolated_test_home():
    """An independent patch outlives other function fixtures and their teardown."""
    with tempfile.TemporaryDirectory(prefix='case-home-', dir=_session.root) as directory, pytest.MonkeyPatch.context() as patch:
        home = Path(directory)
        patch.setenv('HOME', str(home))
        patch.setenv('XDG_CONFIG_HOME', str(home / '.config'))
        patch.setenv('XDG_CACHE_HOME', str(home / '.cache'))
        patch.setenv('XDG_DATA_HOME', str(home / '.local/share'))
        yield home


@pytest.fixture
def synthetic_cwd(tmp_path_factory, monkeypatch):
    """Resolve synthetic IDs/missing inputs away from the checkout's user HOME."""
    directory = tmp_path_factory.mktemp('synthetic-cwd')
    monkeypatch.chdir(directory)
    return directory


@pytest.fixture
def home_guard():
    return _session.guard


def pytest_unconfigure(config):
    _session.close()
