"""Fixed, read-only receipt/output helper; no server installation or procfs.

Requires Python >= 3.6 and Linux descriptor-relative O_PATH/O_NOFOLLOW support.
ENOENT alone means absent. Receipt bytes stay buffered until file identity,
size, timestamps and every ancestor binding have been rechecked.
"""

SCRIPT = r'''
import datetime
import errno
import os
import re
import stat
import sys


class Refusal(Exception):
    pass


def identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def version(info):
    return identity(info) + (info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


class Observation:
    def __init__(self):
        self.fds = []
        self.links = []
        self.stage = 'runtime'

    def close(self):
        for fd in reversed(self.fds):
            os.close(fd)

    def verify(self):
        self.stage = 'directory-identity'
        for parent, name, expected in self.links:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            require(identity(info) == expected, 'DIRECTORY_CHANGED')

    def missing(self, parent, name):
        self.verify()
        self.stage = 'absence-recheck'
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                return
            raise
        raise Refusal('PATH_CHANGED')

    def directory(self, path):
        # O_PATH needs search permission, not directory-listing permission.
        # Keep every ancestor descriptor to verify the same path before reading.
        flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open('/', flags)
        self.fds.append(fd)
        for part in path.split('/')[1:]:
            self.stage = 'directory-stat'
            try:
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)
            except OSError as exc:
                if exc.errno == errno.ENOENT:
                    self.missing(fd, part)
                    return None
                raise
            require(not stat.S_ISLNK(info.st_mode), 'LINK')
            require(stat.S_ISDIR(info.st_mode), 'NOT_DIRECTORY')
            self.stage = 'directory-open'
            child = os.open(part, flags, dir_fd=fd)
            self.fds.append(child)
            require(identity(os.fstat(child)) == identity(info), 'DIRECTORY_CHANGED')
            self.links.append((fd, part, identity(info)))
            fd = child
        self.verify()
        return fd

    def metadata(self, directory, name):
        self.stage = 'file-stat'
        try:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                self.missing(directory, name)
                return None
            raise
        require(not stat.S_ISLNK(info.st_mode), 'LINK')
        require(stat.S_ISREG(info.st_mode), 'NOT_REGULAR')
        self.verify()
        self.stage = 'file-identity'
        after = os.stat(name, dir_fd=directory, follow_symlinks=False)
        require(identity(after) == identity(info), 'FILE_CHANGED')
        return after

    def receipt(self, directory, name):
        info = self.metadata(directory, name)
        if info is None:
            return b'absent\n'
        require(info.st_size <= 4096, 'OVERSIZE')
        self.stage = 'receipt-open'
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        self.fds.append(fd)
        pinned = os.fstat(fd)
        require(stat.S_ISREG(pinned.st_mode), 'NOT_REGULAR')
        require(version(pinned) == version(info), 'FILE_CHANGED')
        self.verify()
        self.stage = 'receipt-read'
        content = b''
        while len(content) < 4097:
            part = os.read(fd, 4097 - len(content))
            if not part:
                break
            content += part
        require(len(content) <= 4096, 'OVERSIZE')
        require(len(content) == info.st_size, 'SIZE_CHANGED')
        require(version(os.fstat(fd)) == version(info), 'FILE_CHANGED')
        self.verify()
        self.stage = 'receipt-identity'
        after = os.stat(name, dir_fd=directory, follow_symlinks=False)
        require(version(after) == version(info), 'FILE_CHANGED')
        return content

    def observe(self, mode, path, names):
        require(mode in ('receipt', 'output'), 'ARGUMENT')
        require(path.startswith('/') and all(p not in ('', '.', '..')
                for p in path.split('/')[1:]), 'ARGUMENT')
        require(names and all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', n)
                              and n not in ('.', '..') for n in names), 'ARGUMENT')
        if mode == 'receipt':
            require(len(names) == 1 and re.fullmatch(r'ag-(start|exit)\.json', names[0]), 'ARGUMENT')
        directory = self.directory(path)
        if directory is None:
            return (b'absent\n' if mode == 'receipt' else
                    ''.join(n + ' absent\n' for n in names).encode('ascii'))
        if mode == 'receipt':
            return self.receipt(directory, names[0])
        rows = []
        for name in names:
            info = self.metadata(directory, name)
            if info is None:
                rows.append(name + ' absent\n')
            else:
                seconds, nanos = divmod(info.st_mtime_ns, 10**9)
                stamp = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)
                rows.append('{} {} {}.{:09d} +0000\n'.format(
                    name, info.st_size, stamp.strftime('%Y-%m-%d %H:%M:%S'), nanos))
        self.verify()
        return ''.join(rows).encode('ascii')


def execute(mode, path, names):
    observation = Observation()
    try:
        require(sys.version_info >= (3, 6), 'PYTHON_VERSION')
        require(all(hasattr(os, name) for name in
                    ('O_PATH', 'O_NOFOLLOW', 'O_NONBLOCK', 'O_DIRECTORY')), 'OS_CAPABILITY')
        require(os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
                and os.stat in os.supports_follow_symlinks, 'OS_CAPABILITY')
        data = observation.observe(mode, path, names)
        return 0, data, ''
    except (OSError, Refusal) as exc:
        category = errno.errorcode.get(exc.errno, 'OSERROR') if isinstance(exc, OSError) else str(exc)
        return 1, b'', 'observation {} {}\n'.format(observation.stage, category)
    finally:
        observation.close()


def main():
    if len(sys.argv) < 4:
        sys.stderr.write('observation arguments ARGUMENT\n')
        return 1
    code, data, error = execute(sys.argv[1], sys.argv[2], sys.argv[3:])
    # Nothing reaches stdout until every check and bounded read succeeds.
    sys.stderr.write(error)
    sys.stdout.buffer.write(data)
    return code


if __name__ == '__main__':
    sys.exit(main())
'''
