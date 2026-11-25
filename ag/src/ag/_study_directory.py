"""Descriptor-bound APFS identities for PBS reservation accounting."""
import ctypes
import errno
import os
import struct
import sys
from hashlib import sha256

# Darwin <sys/attr.h>. Request the returned bitmap so an unsupported
# attribute can never be mistaken for an actual zero-filled value.
_RETURNED = 0x80000000
_OBJECT = 0x10 | 0x200 | 0x02000000  # object tag, birth timespec, file ID
_VOLUME_UUID = 0x00040000
_VOL_INFO = 0x80000000


if sys.platform == 'darwin':
    _libc = ctypes.CDLL(None, use_errno=True)
    _libc.fgetattrlist.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.c_uint]
    _xattr_arguments = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
                        ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    _libc.fgetxattr.argtypes = _libc.fsetxattr.argtypes = _xattr_arguments
    _libc.fgetxattr.restype = ctypes.c_ssize_t


def _attributes(fd, common, volume, payload):
    result = struct.Struct('=6I' + payload)
    request = struct.pack('=HH5I', 5, 0, _RETURNED | common, volume, 0, 0, 0)
    output = ctypes.create_string_buffer(result.size)
    if _libc.fgetattrlist(fd, request, output, result.size, 0) != 0:
        return None
    fields = result.unpack(output)
    if fields[:6] != (result.size, _RETURNED | common, volume & ~_VOL_INFO, 0, 0, 0):
        return None
    return fields[6:]


def apfs_object_digest(fd, inode):
    """Return no persistent evidence on unsupported or snapshot mounts."""
    if sys.platform != 'darwin' or os.fstatvfs(fd).f_flag & os.ST_RDONLY:
        return None
    attributes = _attributes(fd, _OBJECT, 0, 'IqqQ')
    if attributes is None:
        return None
    tag, seconds, nanos, file_id = attributes
    if tag != 25 or file_id != inode or seconds <= 0 or not 0 <= nanos < 10**9:
        return None
    volume = _attributes(fd, 0, _VOL_INFO | _VOLUME_UUID, '16s')
    if volume is None or volume[0] == bytes(16):
        return None
    return sha256(struct.pack('>16sQqq', volume[0], file_id, seconds, nanos)).hexdigest()

# This attribute lives on the new immutable record inode. It is set before
# the O_EXCL writer's fsync, and never added to an existing file or read
# from a user-provided path. Old readers see the same canonical JSON bytes.
_ATTRIBUTE = b'user.ag.pbs-directory-v1'


def _binding(fd, raw, directory_digest):
    source = apfs_object_digest(fd, os.fstat(fd).st_ino)
    if source is None or directory_digest is None:
        return None
    return sha256(bytes.fromhex(source) + sha256(raw).digest() + bytes.fromhex(directory_digest)).digest()


def bind_new(fd, raw, directory_digest):
    binding = _binding(fd, raw, directory_digest)
    if binding is None:
        return
    if sys.platform == 'darwin':
        if _libc.fsetxattr(fd, _ATTRIBUTE, binding, len(binding), 0, 2) != 0:  # XATTR_CREATE
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    else:
        os.setxattr(fd, _ATTRIBUTE, binding, os.XATTR_CREATE)


def matches_binding(fd, raw, directory_digest):
    """None is an unanchored legacy record. A present contradictory seal refuses."""
    try:
        if sys.platform == 'darwin':
            data = ctypes.create_string_buffer(32)
            count = _libc.fgetxattr(fd, _ATTRIBUTE, data, len(data), 0, 0)
            if count < 0:
                code = ctypes.get_errno()
                raise OSError(code, os.strerror(code))
            value = data.raw[:count]
        elif hasattr(os, 'getxattr'):
            value = os.getxattr(fd, _ATTRIBUTE)
        else:
            return None
    except OSError as exc:
        if exc.errno in (getattr(errno, 'ENOATTR', None), getattr(errno, 'ENODATA', None), errno.ENOTSUP):
            return None
        raise
    return value == _binding(fd, raw, directory_digest)
