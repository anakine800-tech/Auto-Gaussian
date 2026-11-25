"""Inspect a legacy PBS event index and optionally install the exact reviewed bytes."""
import argparse
import ctypes
import errno
from hashlib import sha256
import os
import sys
from uuid import uuid4

from ag import _autonomy_store as disk, autonomy_submission as accounting, config


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


def derive(cfg, *, install=None):
    if sys.platform != 'darwin':
        raise ValueError('The legacy PBS event index requires macOS')
    with accounting.machine_lock(create=False):
        with accounting._capture_reads() as reads:
            result, events = accounting._read_pbs_account(cfg, reads, collect_event_index=True)
        if not events:
            raise ValueError('No eligible legacy PBS registrations need an index')
        raw = disk.encode({'schema': 'ag-pbs-directory-event-index/1', 'events': events})
        digest = sha256(raw).hexdigest()
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
