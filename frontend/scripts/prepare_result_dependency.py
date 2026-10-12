"""Assemble pinned source bytes for local integration; never edit owner checkouts.

Development-only: reads git objects and candidate source files, writes a NEW
explicit directory. No database, pip install, imports, or runtime path injection.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def aggregate(files):
    return digest(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args])


def prepare(query_source, result_source, destination):
    manifest = json.loads((Path(__file__).resolve().parents[1] /
                           'docs/result-integration-dependencies.json').read_text())
    overlay = {}
    for key, source in [('query', query_source), ('result', result_source)]:
        spec = manifest[key]
        if git(source, 'rev-parse', 'HEAD').decode().strip() != spec['base']:
            raise ValueError('candidate base mismatch')
        if aggregate(spec['files']) != spec['sha256']:
            raise ValueError('candidate manifest mismatch')
        for name, expected in spec['files'].items():
            data = (source / name).read_bytes()
            if digest(data) != expected:
                raise ValueError('candidate file mismatch: ' + name)
            if name.startswith('auto_g16/'):
                overlay[name] = data
    # All runtime dependencies of both candidates must be byte-identical at base.
    # The only intentional divergences are the pinned overlay files above.
    def archive(source, revision):
        result = {}
        with tarfile.open(fileobj=io.BytesIO(git(source, 'archive', revision, 'auto_g16'))) as tar:
            for entry in tar:
                name = PurePosixPath(entry.name)
                if name.is_absolute() or '..' in name.parts:
                    raise ValueError('unsafe source path')
                if entry.isdir():
                    continue
                if not entry.isfile():
                    raise ValueError('non-regular source entry')
                result[entry.name] = tar.extractfile(entry).read()
        return result
    base = archive(query_source, manifest['query']['base'])
    other = archive(result_source, manifest['result']['base'])
    # Compare the dependency closure, not unrelated Execution successor changes.
    prefixes = ('auto_g16/core/', 'auto_g16/result/', 'auto_g16/observe/')
    names = {name for name in base.keys() | other.keys() if name.startswith(prefixes)}
    if any(base.get(name) != other.get(name) for name in names):
        raise ValueError('owner dependency closure has drifted; integration review required')
    base.update(overlay)
    receipt = {'schema': manifest['schema'], 'query': manifest['query']['sha256'],
               'result': manifest['result']['sha256'],
               'files': {name: digest(data) for name, data in sorted(base.items())}}
    receipt['sha256'] = aggregate(receipt['files'])
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in base.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (destination / 'source-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Prepared pinned local dependency: ' + receipt['sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query-source', required=True, type=Path)
    parser.add_argument('--result-source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    prepare(args.query_source, args.result_source, args.destination)
