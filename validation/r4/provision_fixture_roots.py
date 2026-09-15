"""Create-new directory primitives and a fixed /home-only sudo entrypoint.

The root entrypoint never opens /opt. The launcher uses create_pair as the
ordinary runner for /opt, without chown or a privilege-escalation fallback.
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


def entry(parent, name):
    try:
        s = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return {'state': 'ABSENT'}
    return {'state': 'EXISTS', 'device': s.st_dev, 'inode': s.st_ino,
            'uid': s.st_uid, 'gid': s.st_gid, 'mode': stat.S_IMODE(s.st_mode),
            'type': stat.S_IFMT(s.st_mode)}


def create_pair(parent, prefix, top, leaf, uid, gid, observations, *, transfer_ownership=False):
    """Fresh entries only; normal runner never chowns, root only transfers new FDs."""
    before = entry(parent, top)
    observations.append({'path': prefix + '/' + top, 'before': before})
    check(before['state'] == 'ABSENT', 'existing fixture root: ' + prefix + '/' + top)
    created = []
    try:
        os.mkdir(top, 0o700, dir_fd=parent)
        top_fd = os.open(top, DF, dir_fd=parent)
        created.append((parent, top, top_fd, prefix + '/' + top))
        initial = node(top_fd)
        observations.append({'path': prefix + '/' + top, 'created': initial})
        named = entry(parent, top)
        check((named.get('device'), named.get('inode')) == (initial['device'], initial['inode']), 'new top directory replaced before leaf creation')
        check(initial['uid'] == os.geteuid() and initial['mode'] == 0o700, 'new top directory ownership/mode mismatch')
        if not transfer_ownership:
            check(initial['uid'] == uid and initial['gid'] == gid, 'new runner top directory identity mismatch')
        os.mkdir(leaf, 0o700, dir_fd=top_fd)
        leaf_fd = os.open(leaf, DF, dir_fd=top_fd)
        created.append((top_fd, leaf, leaf_fd, prefix + '/' + top + '/' + leaf))
        initial = node(leaf_fd)
        observations.append({'path': prefix + '/' + top + '/' + leaf, 'created': initial})
        check(initial['uid'] == os.geteuid() and initial['mode'] == 0o700, 'new leaf directory ownership/mode mismatch')
        for parent_fd, name, fd, path in reversed(created):
            expected = os.fstat(fd)
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            check(stat.S_ISDIR(named.st_mode) and (named.st_dev, named.st_ino) == (expected.st_dev, expected.st_ino), 'created directory replaced: ' + path)
            if transfer_ownership:
                os.fchown(fd, uid, gid)
            owned = node(fd)
            observations.append({'path': path, 'owned': owned})
            check(owned['uid'] == uid and owned['gid'] == gid and owned['mode'] == 0o700, 'new directory ownership/mode mismatch: ' + path)
            os.fsync(fd)
    finally:
        for _, _, fd, _ in reversed(created):
            os.close(fd)


def main():
    result = {'status': 'FAIL', 'first_error': None, 'observations': [], 'cleanup_errors': [], 'deletion_permitted': False}
    opened = []
    def expired(signum, frame):
        raise TimeoutError('fixture provisioning hard deadline')
    def observe(item):
        result['observations'].append(item)
        # Save rejection evidence before its predicate, including on root failure.
        print(json.dumps(item, sort_keys=True, separators=(',', ':')), file=sys.stderr, flush=True)
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
        root_info = node(root)
        observe({'path': '/', 'parent': root_info})
        check(root_info['uid'] == 0 and not root_info['mode'] & 0o022, 'untrusted system parent: /')
        observe({'path': '/home', 'entry': entry(root, 'home')})
        home = os.open('home', DF, dir_fd=root)
        opened.append(home)
        info = node(home)
        before = entry(home, 'user100')
        observe({'path': '/home', 'parent': info, 'root_owned': info['uid'] == 0, 'non_group_world_writable': not bool(info['mode'] & 0o022)})
        observe({'path': '/home/user100', 'before': before})
        check(info['uid'] == 0 and not info['mode'] & 0o022, 'untrusted system parent: /home')
        named = entry(root, 'home')
        check((named.get('device'), named.get('inode')) == (info['device'], info['inode']), 'home parent replaced')
        check(before['state'] == 'ABSENT', 'existing fixture root: /home/user100')
        create_pair(home, '/home', 'user100', 'SDL', uid, gid, result['observations'], transfer_ownership=True)
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
