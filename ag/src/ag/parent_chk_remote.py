"""Fixed remote helper text, sent only by the two parent-chk Commands.

Descriptor-relative O_NOFOLLOW prevents directory/file link replacement between
checking and opening. O_EXCL also rejects a racing FIFO or dangling symlink;
shell noclobber alone does not reliably reject all non-regular targets.
Remote Python >= 3.6 and Linux /proc are required; absence fails before qsub.
"""

SCRIPT = r'''
import os
import stat
import subprocess
import sys

def directory(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.split('/'):
            if not part:
                continue
            if part in ('.', '..'):
                raise ValueError('Invalid directory component')
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise

def main():
    mode, source, target = sys.argv[1:]
    source_dir, name = source.rsplit('/', 1)
    directory_fd = directory(source_dir)
    source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    if not stat.S_ISREG(os.fstat(source_fd).st_mode):
        raise ValueError('Parent chk is not a regular file')
    if mode == 'metadata':
        pinned = '/proc/self/fd/' + str(source_fd)
        size = subprocess.check_output(['stat', '-Lc', '%s', '--', pinned], pass_fds=(source_fd,)).decode().strip()
        digest = subprocess.check_output(['sha256sum', '--', pinned], pass_fds=(source_fd,)).decode().split()[0]
        print(size)
        print(digest + '  ' + source)
    elif mode == 'copy':
        target_fd = directory(target)
        # Never open the parent writable. The fixed target cannot name it.
        output_fd = os.open('parent.chk', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=target_fd)
        # Redirections duplicate pinned descriptors; no pathname is reopened or
        # truncated. Leave partial files intact on every failure, including 255.
        subprocess.run(['sh', '-c', 'set -C; cat <&0 >&1'], stdin=source_fd,
                       stdout=output_fd, check=True)
        os.fsync(output_fd)
    else:
        raise ValueError('Invalid chk operation')

try:
    main()
except Exception:
    print('Parent chk operation failed; retain files and stop', file=sys.stderr)
    sys.exit(1)
'''
