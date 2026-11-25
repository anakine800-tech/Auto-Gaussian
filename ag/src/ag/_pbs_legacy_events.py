"""Query positive, exact path/FileID events in the Darwin per-volume journal."""
import ctypes as ct
import fcntl
import os
from pathlib import Path
import struct
import sys
import time


def volume_path(fd):
    """Ask the descriptor for its un-firmlinked path and actual mounted filesystem."""
    if sys.platform != 'darwin':
        raise ValueError('APFS history is unavailable')
    from ag import _study_directory
    output = ct.create_string_buffer(4096)
    returned, vol_info, mountpoint = 0x80000000, 0x80000000, 0x1000
    request = struct.pack('=HH5I', 5, 0, returned, vol_info | mountpoint, 0, 0, 0)
    if _study_directory._libc.fgetattrlist(fd, request, output, len(output), 0):
        raise ValueError('Cannot identify APFS mount point')
    length, common, volume, directory, file, fork, offset, size = struct.unpack_from('=6IiI', output.raw)
    start = 24 + offset
    if ((common, volume, directory, file, fork) != (returned, mountpoint, 0, 0, 0)
            or not 32 <= start < start + size <= length <= len(output)):
        raise ValueError('Incomplete APFS mount point')
    raw_mount = output.raw[start:start + size]
    if not raw_mount.endswith(b'\0'):
        raise ValueError('Invalid APFS mount point')
    mount = Path(os.fsdecode(raw_mount[:-1]))
    physical = Path(os.fsdecode(fcntl.fcntl(fd, 102, bytes(1024)).split(b'\0', 1)[0]))
    if not (mount.is_absolute() and physical.is_absolute()):
        raise ValueError('Missing APFS volume path')
    return str(physical.relative_to(mount)), os.fstat(fd).st_dev


_CALLBACK = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.c_void_p,
                         ct.POINTER(ct.c_uint32), ct.POINTER(ct.c_uint64))


def _function(library, name, result, *arguments):
    fn = getattr(library, name)
    fn.restype, fn.argtypes = result, arguments
    return fn


class _DarwinEvents:
    def __init__(self):
        P, L, U, Q, D = ct.c_void_p, ct.c_long, ct.c_uint32, ct.c_uint64, ct.c_double
        CF = ct.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        FS = ct.CDLL('/System/Library/Frameworks/CoreServices.framework/CoreServices')
        self.string = _function(CF, 'CFStringCreateWithCString', P, P, ct.c_char_p, U)
        self.convert = _function(CF, 'CFStringGetCString', ct.c_bool, P, P, L, U)
        self.array = _function(CF, 'CFArrayCreate', P, P, ct.POINTER(P), L, P)
        self.at = _function(CF, 'CFArrayGetValueAtIndex', P, P, L)
        self.value = _function(CF, 'CFDictionaryGetValue', P, P, P)
        self.number = _function(CF, 'CFNumberGetValue', ct.c_bool, P, L, P)
        self.release = _function(CF, 'CFRelease', None, P)
        self.loop = _function(CF, 'CFRunLoopGetCurrent', P)
        self.run = _function(CF, 'CFRunLoopRunInMode', ct.c_int, P, D, ct.c_bool)
        self.mode = P.in_dll(CF, 'kCFRunLoopDefaultMode').value
        self.get_id = _function(FS, 'FSEventsGetLastEventIdForDeviceBeforeTime', Q, ct.c_int, D)
        self.open = _function(FS, 'FSEventStreamCreateRelativeToDevice', P, P, _CALLBACK, P, ct.c_int, P, Q, D, U)
        self.schedule = _function(FS, 'FSEventStreamScheduleWithRunLoop', None, P, P, P)
        self.start = _function(FS, 'FSEventStreamStart', ct.c_bool, P)
        self.stop = _function(FS, 'FSEventStreamStop', None, P)
        self.invalidate = _function(FS, 'FSEventStreamInvalidate', None, P)
        self.close = _function(FS, 'FSEventStreamRelease', None, P)

    def read(self, scope, dev, earliest, latest, files, *, first_birth):
        lo = self.get_id(dev, earliest)
        hi = self.get_id(dev, latest)
        if not lo or hi <= lo:
            raise ValueError('Historical per-device event interval unavailable')
        return self.read_ids(scope, dev, lo, hi, files, first_birth=first_birth)

    def read_ids(self, scope, dev, lo, hi, files, *, first_birth=False, targets=()):
        flags_utf8 = 0x08000100
        path_key = self.string(None, b'path', flags_utf8)
        file_key = self.string(None, b'fileID', flags_utf8)
        found = []
        outstanding = set(targets)
        done, failed = False, False

        @_CALLBACK
        def receive(stream, context, count, arrays, flags, ids):
            nonlocal done, failed
            try:
                for i in range(count):
                    f, event = flags[i], ids[i]
                    if f & 0x0f:
                        failed = done = True
                        break
                    if f & 0x10:
                        done = True
                        break
                    if event < lo or event > hi:
                        continue
                    row = self.at(arrays, i)
                    name, identifier = self.value(row, path_key), self.value(row, file_key)
                    if not (name and identifier):
                        continue
                    data = ct.create_string_buffer(4096)
                    file_id = ct.c_int64()
                    if not (self.convert(name, data, len(data), flags_utf8) and
                            self.number(identifier, 4, ct.byref(file_id))):  # kCFNumberSInt64Type
                        continue
                    path = os.fsdecode(data.value).lstrip('/')
                    if files.get(path) == file_id.value:
                        found.append((path, event, f))
                        outstanding.discard((path, event))
                        if (first_birth and f & 0x100) or (targets and not outstanding):
                            done = True
                            break
            except Exception:
                failed = done = True  # ctypes callbacks cannot propagate an exception.

        name = self.string(None, os.fsencode(scope), flags_utf8)
        if not name:
            raise ValueError('Invalid historical watch path')
        refs = (ct.c_void_p * 1)(name)
        array = self.array(None, refs, 1, None)
        try:
            stream = self.open(None, receive, None, dev, array, lo, .05, 0x01 | 0x10 | 0x40 | 0x80)
            if not stream:
                raise ValueError('Historical per-device stream unavailable')
            try:
                self.schedule(stream, self.loop(), self.mode)
                if not self.start(stream):
                    raise ValueError('Cannot start historical per-device stream')
                try:
                    deadline = time.monotonic() + 35
                    while not done and time.monotonic() < deadline:
                        self.run(self.mode, .1, True)
                    if not done or failed:
                        raise ValueError('Historical per-device stream incomplete')
                finally:
                    self.stop(stream)
            finally:
                self.invalidate(stream)
                self.close(stream)
        finally:
            self.release(array)
            self.release(name)
            self.release(path_key)
            self.release(file_key)
        return found
