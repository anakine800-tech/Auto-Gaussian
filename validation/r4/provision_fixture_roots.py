"""Finite create-new fixture roots on the ephemeral hosted Linux VM only.

Run once by the reviewed launcher via sudo. No parameters, accounts, software,
existing-path ownership changes, unlink, or recursive operations.
"""
import json
import os
import pwd
import signal
import stat
import sys


DF = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def node(fd):
    s = os.fstat(fd)
    return {'device': s.st_dev, 'inode': s.st_ino, 'uid': s.st_uid, 'gid': s.st_gid, 'mode': stat.S_IMODE(s.st_mode)}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def create_roots(opt_fd, home_fd, uid, gid, observations):
    """Descriptor-only implementation; caller retains validated /opt and /home."""
    # Check both top-level absences before the first mutation.
    for parent, name in ((opt_fd, 'auto-g16-fixtures'), (home_fd, 'user100')):
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            observations.append({'entry': name, 'before': 'ABSENT'})
        else:
            raise FileExistsError('existing fixture root: ' + name)
    created = []
    try:
        for parent, prefix, top, leaf in (
            (opt_fd, '/opt', 'auto-g16-fixtures', 'bin'),
            (home_fd, '/home', 'user100', 'SDL'),
        ):
            os.mkdir(top, 0o700, dir_fd=parent)
            top_fd = os.open(top, DF, dir_fd=parent)
            created.append((parent, top, top_fd, prefix + '/' + top))
            observations.append({'path': prefix + '/' + top, 'created': node(top_fd)})
            os.mkdir(leaf, 0o700, dir_fd=top_fd)
            leaf_fd = os.open(leaf, DF, dir_fd=top_fd)
            created.append((top_fd, leaf, leaf_fd, prefix + '/' + top + '/' + leaf))
            observations.append({'path': prefix + '/' + top + '/' + leaf, 'created': node(leaf_fd)})
        # Child-first ownership transfer; all descriptors were opened at creation.
        for parent, name, fd, path in reversed(created):
            expected = os.fstat(fd)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            check(stat.S_ISDIR(named.st_mode) and (named.st_dev, named.st_ino) == (expected.st_dev, expected.st_ino), 'created directory replaced')
            os.fchown(fd, uid, gid)
            os.fchmod(fd, 0o700)
            os.fsync(fd)
            observations.append({'path': path, 'owned': node(fd)})
    finally:
        for _, _, fd, _ in reversed(created):
            os.close(fd)


def main():
    result = {'status': 'FAIL', 'first_error': None, 'observations': [], 'cleanup_errors': [], 'deletion_permitted': False}
    opened = []
    def expired(signum, frame):
        raise TimeoutError('fixture provisioning hard deadline')
    try:
        check(sys.platform == 'linux' and os.geteuid() == 0, 'ephemeral Linux sudo required')
        check(len(sys.argv) == 1 and sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode, 'fixed isolated invocation required')
        uid = int(os.environ['SUDO_UID'])
        gid = int(os.environ['SUDO_GID'])
        check(uid > 0 and gid >= 0 and os.environ['SUDO_USER'] == 'runner', 'ordinary hosted runner required')
        check(pwd.getpwuid(uid).pw_name == 'runner', 'sudo caller identity mismatch')
        signal.signal(signal.SIGALRM, expired)
        signal.signal(signal.SIGTERM, expired)
        signal.alarm(10)
        root = os.open('/', DF)
        opened.append(root)
        parents = []
        for name in ('opt', 'home'):
            fd = os.open(name, DF, dir_fd=root)
            opened.append(fd)
            info = node(fd)
            check(info['uid'] == 0 and not info['mode'] & 0o022, 'untrusted system parent')
            parents.append(fd)
            result['observations'].append({'path': '/' + name, 'parent': info})
        create_roots(*parents, uid, gid, result['observations'])
        result.update(status='PASS', runner_uid=uid, runner_gid=gid)
    except BaseException as exc:
        result['first_error'] = repr(exc)
    finally:
        signal.alarm(0)
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError as exc:
                result['cleanup_errors'].append(repr(exc))
        if result['cleanup_errors']:
            result['status'] = 'FAIL'
        print(json.dumps(result, sort_keys=True, separators=(',', ':')), flush=True)
    return 0 if result['status'] == 'PASS' else 125


if __name__ == '__main__':
    sys.exit(main())
