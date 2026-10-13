import importlib.util
from pathlib import Path

import numpy as np
import pytest
from cclib.io import ccread

spec = importlib.util.spec_from_file_location('sanitize_log', Path(__file__).parents[1]/'tools'/'sanitize_log.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sanitize_log = module.sanitize_log


@pytest.mark.parametrize('fixture', ['water_opt_freq.log', 'butane_anti_freq.log', 'butane_gauche_freq.log'])
def test_sanitization_preserves_parser(tmp_path, fixture):
    original = Path(__file__).parent/'fixtures'/fixture
    text = original.read_text().replace('GINC-HOST', 'GINC-PRIVATEHOST').replace('\\USER\\', '\\PRIVATEUSER\\')
    text = text.replace('PATH/l1.exe', '/' + 'private-install/l1.exe').replace('PID=     0.', 'PID=     34567.')
    raw, clean = tmp_path/'raw.log', tmp_path/'clean.log'
    raw.write_text(text)
    cleaned = sanitize_log(text)
    clean.write_text(cleaned)
    assert 'PRIVATEHOST' not in cleaned and 'PRIVATEUSER' not in cleaned
    assert '34567' not in cleaned and 'private-install' not in cleaned
    before, after = ccread(str(raw)), ccread(str(clean))
    for field in ('scfenergies', 'vibfreqs', 'atomcoords', 'vibdisps'):
        np.testing.assert_array_equal(getattr(before, field), getattr(after, field))


def test_paths_identifiers_and_no_overwrite(tmp_path):
    text = (' Enter /' + 'scratch/private/a.log PID= 7788\n'
            ' Hostname=PRIVATEHOST Username=PRIVATEUSER\n'
            ' C:\\private\\job.log\n')
    cleaned = sanitize_log(text)
    for value in ('private', 'PRIVATEHOST', 'PRIVATEUSER', '7788'):
        assert value not in cleaned
    source, destination = tmp_path/'raw', tmp_path/'clean'
    source.write_text(text)
    module.main([str(source), str(destination)])
    with pytest.raises(FileExistsError):
        module.main([str(source), str(destination)])
