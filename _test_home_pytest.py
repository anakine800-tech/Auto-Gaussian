"""Shared pytest hooks; child Python bootstrap has no pytest dependency."""
from pathlib import Path
import sys
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
def isolated_test_home(tmp_path):
    """An independent patch outlives other function fixtures and their teardown."""
    home = tmp_path / 'isolated-home'
    home.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('HOME', str(home))
        patch.setenv('XDG_CONFIG_HOME', str(home / '.config'))
        patch.setenv('XDG_CACHE_HOME', str(home / '.cache'))
        patch.setenv('XDG_DATA_HOME', str(home / '.local/share'))
        yield home


@pytest.fixture
def home_guard():
    return _session.guard


def pytest_unconfigure(config):
    _session.close()
