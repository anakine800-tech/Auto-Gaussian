"""Build an installable local candidate with a frozen Vite bundle.

Run after pnpm build, using Python with setuptools 82.0.1. This is a local
artifact build, not package publication. The output directory must be new.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
import tomllib


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(destination):
    if version('setuptools') != '82.0.1':
        raise RuntimeError('build requires setuptools==82.0.1')
    root = Path(__file__).resolve().parents[1]
    sources = {'pyproject.toml': (root / 'pyproject.toml').read_bytes()}
    sources.update({str(p.relative_to(root)): p.read_bytes() for p in sorted((root / 'autog_frontend').glob('*.py'))})
    ui = root / 'web/dist'
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('build_static_ui', root / 'autog_frontend/static_ui.py')
    loader = module_from_spec(spec)
    spec.loader.exec_module(loader)
    bundle = loader.load_ui(ui)  # Same trusted asset allowlist as runtime.
    for url, (content, _) in bundle.items():
        sources['autog_frontend/ui/' + ('index.html' if url == '/' else url.lstrip('/'))] = content
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='autog-wheel-build-') as directory:
        stage = Path(directory).resolve()
        for name, content in sources.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        subprocess.run([sys.executable, '-B', '-c',
                        'from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])',
                        str(destination)], cwd=stage, check=True,
                       env={**os.environ, 'SOURCE_DATE_EPOCH': '1789776000', 'PYTHONDONTWRITEBYTECODE': '1'})
    wheels = list(destination.glob('*.whl'))
    if len(wheels) != 1:
        raise RuntimeError('expected one frontend wheel')
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        for name, content in sources.items():
            if name.startswith('autog_frontend/') and archive.read(name) != content:
                raise RuntimeError('wheel payload mismatch')
    files = {name: sha(content) for name, content in sorted(sources.items())}
    receipt = {'schema': 'autog-frontend-wheel/1', 'version': tomllib.loads(sources['pyproject.toml'].decode())['project']['version'],
               'builder': 'setuptools==82.0.1', 'files': files,
               'source_sha256': sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()),
               'wheel': wheel.name, 'wheel_sha256': sha(wheel.read_bytes())}
    (destination / 'frontend-wheel-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'wheel': wheel.name, 'sha256': receipt['wheel_sha256']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    build(parser.parse_args().output_dir)
