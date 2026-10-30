"""Default isolation for combined and Skills pytest entry points."""
from pathlib import Path

import _test_home_pytest as isolation

isolation.start_session(Path(__file__).resolve().parent)


@isolation.pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if not config.pluginmanager.is_registered(isolation):
        config.pluginmanager.register(isolation, 'ag-test-home-isolation')
