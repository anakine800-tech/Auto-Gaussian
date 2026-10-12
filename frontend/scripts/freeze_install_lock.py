"""Freeze a bounded offline wheelhouse; reject missing/unexpected distributions.

The backend/ frontend SHA arguments must come from their reviewed build
receipts. Third-party versions come from requirements.lock.txt. This records
actual downloaded artifact hashes; it is not an upstream supply-chain audit.
"""
import argparse
from email.parser import BytesParser
import hashlib
import re
from pathlib import Path
import zipfile
import tomllib


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def freeze(wheelhouse, backend_sha, frontend_sha, output):
    for value in (backend_sha, frontend_sha):
        if not re.fullmatch('[0-9a-f]{64}', value):
            raise ValueError('expected a reviewed wheel SHA-256')
    root = Path(__file__).resolve().parents[1]
    expected = {canonical(name): version for name, version in
                (line.split('==') for line in (root / 'requirements.lock.txt').read_text().splitlines() if line)}
    expected.update({'auto-g16': '2.7.0', 'autog-frontend-readonly': tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']})
    pins = {'auto-g16': backend_sha, 'autog-frontend-readonly': frontend_sha}
    found = {}
    for wheel in sorted(wheelhouse.glob('*.whl')):
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as archive:
            names = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
            if len(names) != 1:
                raise ValueError('ambiguous wheel metadata')
            metadata = BytesParser().parsebytes(archive.read(names[0]))
        name, version = canonical(metadata['Name']), metadata['Version']
        if name not in expected or expected[name] != version or name in found:
            raise ValueError('unexpected distribution or version: ' + name)
        if name in pins and pins[name] != digest:
            raise ValueError('reviewed wheel hash mismatch: ' + name)
        found[name] = f'{name}=={version} --hash=sha256:{digest}'
    if found.keys() != expected.keys():
        raise ValueError('incomplete wheelhouse')
    with output.open('x') as stream:
        stream.write('# Local macOS x86_64 / CPython 3.13 candidate, not a public release.\n')
        stream.write('\n'.join(found[name] for name in sorted(found)) + '\n')
    print('Frozen', len(found), 'wheel artifacts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheelhouse', type=Path, required=True)
    parser.add_argument('--backend-sha256', required=True)
    parser.add_argument('--frontend-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze(args.wheelhouse, args.backend_sha256, args.frontend_sha256, args.output)
