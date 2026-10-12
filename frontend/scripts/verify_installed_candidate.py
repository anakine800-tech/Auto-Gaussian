"""Verify installed versions and product runtime bytes against the local lock."""
import argparse
import hashlib
from importlib.metadata import distribution, version
import json
from pathlib import Path
import re
import zipfile


def verify(wheelhouse, lock):
    expected = {}
    for line in lock.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([a-z0-9-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})', line)
        if match is None:
            raise ValueError('unsupported lock line')
        name, wanted, digest = match.groups()
        if name in expected or version(name) != wanted:
            raise ValueError('installed distribution version mismatch')
        expected[name] = (wanted, digest)
    import auto_g16, autog_frontend
    for module in (auto_g16, autog_frontend):
        if 'site-packages' not in module.__file__:
            raise ValueError('candidate must be installed, not a source checkout')
    checked = {}
    for name, package in [('auto-g16', 'auto_g16'), ('autog-frontend-readonly', 'autog_frontend')]:
        wanted, digest = expected[name]
        wheel = wheelhouse / f"{name.replace('-', '_')}-{wanted}-py3-none-any.whl"
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != digest:
            raise ValueError('locked wheel hash mismatch')
        installed = distribution(name)
        count = 0
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.namelist():
                if member.startswith(package + '/') and not member.endswith('/'):
                    if Path(installed.locate_file(member)).read_bytes() != archive.read(member):
                        raise ValueError('installed runtime bytes differ from wheel')
                    count += 1
        if count == 0:
            raise ValueError('empty runtime payload')
        checked[name] = {'version': wanted, 'wheel_sha256': digest, 'runtime_files_verified': count}
    return {'schema': 'autog-installed-candidate-verification/1', 'status': 'PASS',
            'locked_versions_verified': len(expected), 'products': checked}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wheelhouse', type=Path, required=True)
    p.add_argument('--lock', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(verify(args.wheelhouse, args.lock), indent=2, sort_keys=True))
