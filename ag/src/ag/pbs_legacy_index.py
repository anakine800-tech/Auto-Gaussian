"""Inspect a legacy PBS event index and optionally install the exact reviewed bytes."""
import argparse
import ctypes
import errno
from hashlib import sha256
import os
from pathlib import Path
import sys
from uuid import uuid4

from ag import _autonomy_store as disk, autonomy_submission as accounting, config, study
from ag._pbs_legacy_directories import LegacyDirectories


def _install(store, raw):
    name = 'pbs-legacy-event-index.json'
    try:
        existing = store.read(name)
    except FileNotFoundError:
        pass
    else:
        if existing != raw:
            raise ValueError('Different existing PBS event index; preserve it for local review')
        os.fsync(store.fd)
        return
    stage = '.pbs-legacy-index-' + uuid4().hex
    store.exclusive(stage, raw)
    if store.read(stage) != raw:
        raise ValueError('Staged PBS event index changed before publication')
    rename = ctypes.CDLL(None, use_errno=True).renameatx_np
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if rename(store.fd, os.fsencode(stage), store.fd, os.fsencode(name), 0x4):  # Darwin RENAME_EXCL
        code = ctypes.get_errno()
        if code != errno.EEXIST or store.read(name) != raw:
            raise OSError(code, 'Exclusive publication of the PBS event index failed')
    os.fsync(store.fd)


def _list(path, reads):
    fd = disk.directory(path)
    try:
        reads.directory(path, fd)
        return sorted(os.listdir(fd))
    finally:
        os.close(fd)


def _discover(reads):
    # This pass discovers only lookup hints. It neither locks writer claims
    # nor uses a provisional scan to release any resources.
    verifier = LegacyDirectories(reads, collect=True)
    registry = Path.home() / '.config/ag/manual-writers'
    for key in _list(registry, reads):
        bucket = registry / key
        groups = set()
        for name in _list(bucket, reads):
            if not name.endswith('.claim.json'):
                continue
            source = bucket / name
            raw = accounting._read_file(source)
            record = accounting._json(raw)
            if not isinstance(record, dict) or not isinstance(record.get('study_path'), str):
                raise ValueError('Malformed writer study path during PBS event discovery')
            path = Path(record['study_path'])
            if not path.is_absolute() or '..' in path.parts:
                raise ValueError('Invalid writer study path during PBS event discovery')
            study.identifier(path.name)
            live = accounting.study_identity(path, apfs=True)
            if live['study_key'] != key or record.get('study_key') != key:
                raise ValueError('Writer bucket does not identify the original study')
            old = record.get('study_device')
            if type(old) is not int or record.get('study_inode') != live['study_inode']:
                raise ValueError('Writer does not identify the current study inode')
            if old == live['study_device'] or old in groups:
                continue
            if 'apfs_directory_sha256' not in live:
                raise ValueError('Original APFS directory evidence is unavailable')
            if verifier._needs_recovery(source, record, raw, live, old):
                if not verifier.matches(path, record, raw, source, live):
                    raise ValueError('Original PBS directory discovery failed')
                groups.add(old)
    return verifier.lookup


def derive(cfg, *, install=None):
    if sys.platform != 'darwin':
        raise ValueError('The legacy PBS event index requires macOS')
    with accounting._capture_reads() as discovered:
        events = _discover(discovered)
    if not events:
        raise ValueError('No eligible legacy PBS registrations need an index')
    raw = disk.encode({'schema': 'ag-pbs-directory-event-index/1', 'events': events})
    digest = sha256(raw).hexdigest()
    with accounting.machine_lock(create=False):
        discovered.verify()
        with accounting._capture_reads() as reads:
            result = accounting._read_pbs_account(cfg, reads, event_index=raw)
        discovered.verify()
        if install is not None:
            if digest != install:
                raise ValueError('Verified event index differs from the reviewed digest')
            with accounting._machine_directory(create=False) as store:
                _install(store, raw)
        return dict(sha256=digest, indexed_objects=len(events), placements=len(result['placements']),
                    installed=install is not None)


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', metavar='REVIEWED_SHA256',
                        help='exclusively create the fixed new index after repeating the full local check')
    args = parser.parse_args()
    try:
        print(json.dumps(derive(config.load_config(), install=args.install), sort_keys=True))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
