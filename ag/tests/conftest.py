"""ag/pyproject.toml can stop pytest before the repository-root conftest."""
from pathlib import Path
import sys
import pytest

_repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo))
import _test_home_pytest as isolation

isolation.start_session(_repo)


@isolation.pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if not config.pluginmanager.is_registered(isolation):
        config.pluginmanager.register(isolation, 'ag-test-home-isolation')


@pytest.fixture
def butane_xyz(tmp_path_factory):
    """Keep optional facts/manifest probes beside a disposable input copy."""
    path = tmp_path_factory.mktemp('butane-input') / 'butane.xyz'
    path.write_bytes((_repo / 'ag/tests/data/butane.xyz').read_bytes())
    return path
