"""Independent fixed-entry Linux observations. Facts only; never issues valid Q."""
import hashlib
import os
from pathlib import Path
import re
import stat
import sys


def read_regular(path, cap):
    parts = Path(path).parts
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in parts[1:-1]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        item = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            before = os.fstat(item)
            assert stat.S_ISREG(before.st_mode)
            raw = bytearray()
            while len(raw) <= cap:
                block = os.read(item, min(65536, cap + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            after = os.fstat(item)
            named = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            assert (after.st_dev, after.st_ino) == (named.st_dev, named.st_ino)
            assert len(raw) <= cap
            return bytes(raw)
        finally:
            os.close(item)
    finally:
        os.close(fd)


def node(s):
    return {'device': s.st_dev, 'inode': s.st_ino}


def unescape(s):
    assert not re.search(r'\\(?!040|011|012|134)', s)
    return re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), s)


def mounts(raw):
    rows = []
    for line in raw.decode('utf-8').splitlines():
        left, right = line.split(' - ')
        a, b = left.split(), right.split()
        assert len(a) >= 6 and len(b) == 3
        major, minor = map(int, a[2].split(':'))
        rows.append(dict(mount_id=int(a[0]), device_major=major, device_minor=minor,
                         root=unescape(a[3]), mount_point=unescape(a[4]),
                         filesystem_type=unescape(b[0]), source=unescape(b[1]),
                         mount_options=sorted(set(a[5].split(','))),
                         super_options=sorted(set(b[2].split(',')))))
    return rows


def location(role, path, rows):
    assert path == os.path.normpath(path) and path.startswith('/')
    fds = [os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    try:
        parts = Path(path).parts[1:]
        for part in parts[:-1]:
            fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if role in {'workspace-root', 'xtb-data-root'}:
            flags |= os.O_DIRECTORY
        obj = os.open(parts[-1], flags, dir_fd=fds[-1])
        try:
            st = os.fstat(obj)
            named = os.stat(parts[-1], dir_fd=fds[-1], follow_symlinks=False)
            assert node(st) == node(named)
            candidates = [m for m in rows if m['mount_point'] == '/' or path == m['mount_point'] or path.startswith(m['mount_point'] + '/')]
            longest = max(len(m['mount_point']) for m in candidates)
            selected = [m for m in candidates if len(m['mount_point']) == longest]
            assert len(selected) == 1
            mount = selected[0]
            assert (os.major(st.st_dev), os.minor(st.st_dev)) == (mount['device_major'], mount['device_minor'])
            return dict(role=role, path=path, parent_chain=[node(os.fstat(fd)) for fd in fds], object=node(st), mount=mount)
        finally:
            os.close(obj)
    finally:
        for fd in reversed(fds):
            os.close(fd)


def observe(runtime, remote_root, data_root, semantic):
    assert sys.platform == 'linux', 'No Darwin/mock fallback'
    machine_raw = read_regular('/etc/machine-id', 4096)
    boot_raw = read_regular('/proc/sys/kernel/random/boot_id', 128)
    # Numeric current-process path retains no-follow traversal through procfs.
    mount_raw = read_regular(f'/proc/{os.getpid()}/mountinfo', 4 * 1024 * 1024)
    machine = hashlib.sha256(machine_raw).hexdigest()
    boot = boot_raw.decode('ascii').removesuffix('\n')
    assert re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', boot)
    uname = os.uname()
    host = dict(host_key=semantic({'machine_id_sha256': machine}), machine_id_sha256=machine,
                boot_id=boot, kernel_release=uname.release, architecture=uname.machine,
                namespaces={'mount': node(os.stat('/proc/self/ns/mnt')), 'pid': node(os.stat('/proc/self/ns/pid'))},
                locations=[location(role, str(path), mounts(mount_raw)) for role, path in zip(
                    ('workspace-root', 'server-python', 'xtb', 'xtb-data-root'),
                    (remote_root, runtime['server_python']['path'], runtime['xtb']['path'], data_root))])
    for key in ('server_python', 'xtb'):
        entry = runtime[key]
        raw = read_regular(entry['path'], 64 * 1024 * 1024)
        assert len(raw) == entry['size_bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256']
    return host, {'machine-id.raw': machine_raw, 'boot-id.raw': boot_raw, 'mountinfo.raw': mount_raw}
