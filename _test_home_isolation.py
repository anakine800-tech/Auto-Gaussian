"""Test-only protection against the T188 real-home registry accident.

This is a Python regression guard, not an OS sandbox. See DEVELOPING.md for
the deliberately narrow source/runtime exceptions and external-process limits.
"""
from contextlib import contextmanager
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import threading


class HomeAccessError(BaseException):
    """Escape production OSError/Exception recovery; pytest reports a failure."""


def inside(path, root):
    return path == root or path.startswith(root + os.sep)


def runtime_trees():
    runtime = sysconfig.get_paths()
    trees = {runtime[key] for key in ('stdlib', 'platstdlib', 'purelib', 'platlib')}
    # Conda's compiled TZPATH includes both fixed timezone directories below.
    # Dependency/standard timezone data can live outside site-packages.
    # RDBASE, PYTHONTZPATH and TZDIR must not grant access to user data.
    trees.update(str(Path(prefix) / relative)
                 for prefix in {sys.prefix, sys.base_prefix}
                 for relative in ('share/RDKit/Data', 'share/zoneinfo', 'share/tzinfo'))
    import gettext
    trees.add(gettext._default_localedir)  # argparse's installed translations only
    return trees


class HomeGuard:
    def __init__(self, homes, files=(), trees=(), repo=None, bootstrap=None):
        self.homes = tuple(map(os.path.abspath, homes))
        self.files = frozenset(map(os.path.abspath, files))
        self.trees = tuple(map(os.path.abspath, trees))
        self.repo = repo
        self.bootstrap = bootstrap
        self.parents = set()
        for path in (*self.files, *self.trees):
            self.parents.update(map(str, Path(path).parents))
        self.source_paths = self.parents | self.files
        self.active = False
        self.local = threading.local()
        self.originals = []
        self.raw_readlink = os.readlink

    def lexical(self, path, access):
        if not any(inside(path, home) for home in self.homes):
            return
        if access != 'write':
            if path in self.files or any(inside(path, root) for root in self.trees):
                return
            candidate = Path(path)
            if candidate.parent.name == '__pycache__':
                source = candidate.parent.parent / (candidate.name.split('.')[0] + '.py')
                if str(source) in self.files:
                    return
            if access == 'metadata' and self.repo and inside(path, self.repo):
                if candidate.parts[-2:] == ('conda-meta', 'history') and str(candidate.parent.parent) in self.source_paths:
                    return
                if str(candidate.parent) in self.source_paths and candidate.name in (
                    '__init__.py', 'conftest.py', '__pycache__', 'pyvenv.cfg', 'conda-meta',
                ):
                    return
            if access == 'metadata' and path in self.parents:
                return
            # Enumerate only source directories, never the home or its ancestors.
            if access == 'list' and path in self.parents and self.repo and inside(path, self.repo):
                return
        relative = (os.path.relpath(path, self.repo) if self.repo and inside(path, self.repo)
                    else '<protected-home>/' + os.path.relpath(path, next(h for h in self.homes if inside(path, h))))
        raise HomeAccessError(f'test HOME isolation blocked {access}: {relative}')

    def fd_path(self, fd):
        if sys.platform == 'darwin':
            import fcntl
            try:
                return os.fsdecode(fcntl.fcntl(fd, 50, bytes(1024)).split(b'\0', 1)[0])
            except OSError:
                return None  # pipes/sockets have no filesystem path
        try:
            path = self.raw_readlink(f'/proc/self/fd/{fd}')
        except OSError:
            return None
        return path.removesuffix(' (deleted)') if path.startswith('/') else None

    def check(self, path, access='read', dir_fd=None):
        if not self.active or path is None:
            return
        if isinstance(path, int):
            path = self.fd_path(path)
            if path is None:
                return
        path = os.fsdecode(path)
        if not os.path.isabs(path) and dir_fd not in (None, -1):
            base = self.fd_path(dir_fd)
            if base is None:
                raise HomeAccessError('test HOME isolation cannot resolve directory descriptor')
            path = os.path.join(base, path)
        path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
        self.lexical(os.path.normpath(path), access)
        if getattr(self.local, 'resolving', False):
            return
        # lstat/readlink wrappers check each component BEFORE resolving symlinks.
        self.local.resolving = True
        try:
            resolved = os.path.realpath(path)
        finally:
            self.local.resolving = False
        self.lexical(resolved, access)

    def audit(self, event, args):
        if not self.active:
            return
        if event == 'open':
            if getattr(self.local, 'checked_open', False):
                return  # os.open wrapper already checked its dir_fd
            path, mode, flags = args
            write = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            self.check(path, 'write' if write else 'read')
        elif event in ('os.listdir', 'os.scandir'):
            self.check(args[0] if args[0] is not None else '.', 'list')
        elif event == 'os.chdir':
            self.check(args[0], 'metadata')
        elif event in ('os.remove', 'os.rmdir'):
            self.check(args[0], 'write', args[1])
        elif event in ('os.mkdir', 'os.chmod', 'os.chown', 'os.utime'):
            self.check(args[0], 'write', args[-1])
        elif event == 'os.truncate':
            self.check(args[0], 'write')
        elif event in ('os.rename', 'os.link'):
            self.check(args[0], 'write', args[2])
            self.check(args[1], 'write', args[3])
        elif event == 'os.symlink':
            self.check(args[1], 'write', args[2])

    def patch(self, obj, name, replacement):
        original = getattr(obj, name)
        self.originals.append((obj, name, original))
        setattr(obj, name, replacement)
        if obj is os:
            for capability in ('supports_dir_fd', 'supports_fd', 'supports_follow_symlinks', 'supports_effective_ids'):
                supported = getattr(os, capability, set())
                if original in supported:
                    self.originals.append((os, capability, supported))
                    setattr(os, capability, supported | {replacement})

    def install(self):
        # An interpreter's editable .pth can point at a different, private checkout.
        # Do not grant that source tree access just to satisfy import path probing.
        sys.path[:] = [entry for entry in sys.path if (
            not any(inside(os.path.abspath(entry), home) for home in self.homes)
            or os.path.abspath(entry) in self.files
            or any(inside(os.path.abspath(entry), tree) for tree in self.trees)
            or self.repo and inside(os.path.abspath(entry), self.repo) and os.path.abspath(entry) in self.parents
        )]
        # Audit events also catch saved references to builtins.open/io.open.
        sys.addaudithook(self.audit)
        for name in ('stat', 'lstat', 'readlink', 'access'):
            original = getattr(os, name)

            @functools.wraps(original)
            def metadata(path, *args, _original=original, **kwargs):
                self.check(path, 'metadata', kwargs.get('dir_fd'))
                return _original(path, *args, **kwargs)

            self.patch(os, name, metadata)
        original_open = os.open

        @functools.wraps(original_open)
        def open_fd(path, flags, mode=0o777, *, dir_fd=None):
            write = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            self.check(path, 'write' if write else 'read', dir_fd)
            self.local.checked_open = True
            try:
                return original_open(path, flags, mode, dir_fd=dir_fd)
            finally:
                self.local.checked_open = False

        self.patch(os, 'open', open_fd)
        original_scandir = os.scandir
        guard = self

        class CheckedEntry:
            def __init__(self, entry, base):
                self.entry, self.base = entry, base

            def __fspath__(self):
                return os.fspath(self.entry)

            def __getattr__(self, name):
                value = getattr(self.entry, name)
                if name in ('stat', 'is_file', 'is_dir', 'is_symlink', 'inode'):
                    def checked(*args, **kwargs):
                        path = os.path.join(self.base, os.fsdecode(self.entry.name))
                        if name in ('is_file', 'is_dir', 'is_symlink'):
                            # Type information belongs to the permitted enumeration;
                            # it does not grant access to an entry's contents/children.
                            guard.check(self.base, 'list')
                            if name != 'is_symlink' and kwargs.get('follow_symlinks', True) and self.entry.is_symlink():
                                guard.check(path, 'metadata')
                        else:
                            guard.check(path, 'metadata')
                        return value(*args, **kwargs)
                    return checked
                return value

        class CheckedScandir:
            def __init__(self, path):
                self.base = guard.fd_path(path) if isinstance(path, int) else os.path.abspath(os.fsdecode(path or '.'))
                self.entries = original_scandir(path)

            def __iter__(self):
                return self

            def __next__(self):
                return CheckedEntry(next(self.entries), self.base)

            def close(self):
                self.entries.close()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        self.patch(os, 'scandir', lambda path='.': CheckedScandir(path))
        for name, access in (('read', 'read'), ('write', 'write'), ('fstat', 'metadata')):
            original = getattr(os, name)

            @functools.wraps(original)
            def descriptor(fd, *args, _original=original, _access=access, **kwargs):
                self.check(fd, _access)
                return _original(fd, *args, **kwargs)

            self.patch(os, name, descriptor)
        if self.bootstrap:
            original_init = subprocess.Popen.__init__
            signature = inspect.signature(original_init)

            @functools.wraps(original_init)
            def popen(process, *args, **kwargs):
                bound = signature.bind(process, *args, **kwargs)
                supplied_env = bound.arguments.get('env')
                env = dict(os.environ if supplied_env is None else supplied_env)
                env = self.child_environment(env)
                argv = bound.arguments['args']
                if isinstance(argv, (list, tuple)) and argv:
                    executable = os.path.basename(os.fsdecode(bound.arguments.get('executable') or argv[0]))
                    if executable.startswith('python'):
                        options = iter(argv[1:])
                        for option in options:
                            option = os.fsdecode(option)
                            if not option.startswith('-') or option == '--' or option.startswith(('-c', '-m')):
                                break
                            if option in ('-W', '-X', '--check-hash-based-pycs'):
                                next(options, None)
                                continue
                            if option.startswith(('-W', '-X')):
                                continue
                            if not option.startswith('--') and any(flag in option[1:] for flag in 'EIS'):
                                raise HomeAccessError('Python child disables test HOME bootstrap')
                    self.check_git(argv, bound.arguments.get('cwd'))
                self.check(bound.arguments.get('cwd'), 'metadata')
                for fd in bound.arguments.get('pass_fds', ()):
                    self.check(fd)
                bound.arguments['env'] = env
                return original_init(*bound.args, **bound.kwargs)

            self.patch(subprocess.Popen, '__init__', popen)
        self.active = True
        return self

    def check_git(self, argv, cwd):
        if os.path.basename(os.fsdecode(argv[0])) != 'git':
            return
        args = list(argv[1:])
        root = os.path.abspath(cwd or os.getcwd())
        if args[:1] == ['-C']:
            root = os.path.abspath(args[1])
            args = args[2:]
        self.check(root, 'metadata')
        root = os.path.realpath(root)
        if any(inside(root, home) for home in self.homes):
            allowed = (
                ['rev-parse', 'HEAD'], ['rev-parse', '--show-toplevel'],
                ['status', '--porcelain', '--untracked-files=normal'],
                ['status', '--porcelain', '--untracked-files=normal', '--', 'ag/src', 'ag/pyproject.toml'],
            )
            if not self.repo or not inside(root, self.repo) or args not in allowed:
                raise HomeAccessError('Only read-only checkout Git provenance is allowed')

    def child_environment(self, env):
        self.check(env.get('HOME', os.environ['HOME']), 'write')
        env['HOME'] = env.get('HOME', os.environ['HOME'])
        env['PYTHONPATH'] = os.pathsep.join(filter(None, (
            self.bootstrap, str(Path(self.repo) / 'ag/src'), env.get('PYTHONPATH'),
        )))
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['GIT_OPTIONAL_LOCKS'] = '0'
        env['GIT_CONFIG_NOSYSTEM'] = '1'
        env['GIT_CONFIG_GLOBAL'] = os.devnull
        policy = json.dumps(dict(
            homes=self.homes, files=list(self.files), trees=self.trees,
            repo=self.repo, bootstrap=self.bootstrap,
        ))
        # A repository file list can exceed Linux's per-environment-string limit.
        policy_path = Path(self.bootstrap) / (hashlib.sha256(policy.encode()).hexdigest() + '.json')
        try:
            with policy_path.open('x') as stream:
                stream.write(policy)
        except FileExistsError:
            pass
        env['_AG_TEST_HOME_POLICY'] = str(policy_path)
        return env

    def close(self):
        self.active = False
        for obj, name, original in reversed(self.originals):
            setattr(obj, name, original)
        self.originals.clear()

    @contextmanager
    def protect_synthetic_home(self, path):
        """Negative tests add a disposable sentinel root; never replace real roots."""
        previous = self.homes
        self.homes = (*previous, os.path.abspath(path))
        try:
            yield
        finally:
            self.homes = previous


class TestHomeSession:
    def __init__(self, repo):
        self.environment = dict(os.environ)
        self.bytecode = sys.dont_write_bytecode
        self.python_path = list(sys.path)
        # Only capture the path identity. Never enumerate or open the user's home.
        real_home = str(Path.home())
        inherited = sys.modules.get('sitecustomize')
        inherited_guard = getattr(inherited, '_guard', None)
        homes = inherited_guard.homes if inherited_guard else [real_home]
        if inherited_guard:
            inherited_guard.close()  # replace, do not stack Python wrappers
        self.temporary = tempfile.TemporaryDirectory(prefix='ag-test-home-')
        self.root = Path(self.temporary.name).resolve()
        if inside(str(self.root), real_home):
            raise HomeAccessError('Test temporary directory must be outside the original HOME')
        self.repo = str(repo)
        files = subprocess.check_output(
            ['git', '-C', self.repo, 'ls-files', '-z'],
            env=dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull),
        ).decode().split('\0')
        files = [str(repo / path) for path in files if path]
        # Editable setuptools metadata is generated, not tracked source. Only
        # these package-discovery files are needed; the directory is not exempt.
        files += [str(repo / 'ag/src/ag.egg-info' / name) for name in (
            'PKG-INFO', 'SOURCES.txt', 'entry_points.txt', 'top_level.txt',
            'dependency_links.txt', 'requires.txt',
        )]
        trees = runtime_trees()
        files += [sys.executable, os.path.realpath(sys.executable), str(Path(sys.prefix) / 'pyvenv.cfg')]
        files += [str(Path(prefix) / 'bin' / name)
                  for prefix in {sys.prefix, sys.base_prefix} for name in ('ag', 'pytest')]
        # The zip stdlib path is a file, not a blanket sys.path exception.
        files += [p for p in sys.path if p.endswith('.zip')]
        self.bootstrap = self.root / 'bootstrap'
        self.bootstrap.mkdir()
        (self.bootstrap / '_ag_test_home_guard.py').write_text(Path(__file__).read_text())
        (self.bootstrap / 'sitecustomize.py').write_text(
            'import json, os\n'
            'try:\n'
            '    from _ag_test_home_guard import HomeGuard\n'
            '    with open(os.environ["_AG_TEST_HOME_POLICY"]) as _stream:\n'
            '        _guard = HomeGuard(**json.load(_stream)).install()\n'
            'except BaseException:\n'
            '    os._exit(91)\n'
        )
        session_home = self.root / 'collection-home'
        session_home.mkdir()
        os.environ['HOME'] = str(session_home)
        for key, relative in (('XDG_CONFIG_HOME', '.config'), ('XDG_CACHE_HOME', '.cache'),
                              ('XDG_DATA_HOME', '.local/share')):
            os.environ[key] = str(session_home / relative)
        self.guard = HomeGuard(homes, files, trees, self.repo, str(self.bootstrap)).install()
        os.environ.update(self.guard.child_environment(dict(os.environ)))
        sys.dont_write_bytecode = True
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.guard.close()
        sys.dont_write_bytecode = self.bytecode
        sys.path[:] = self.python_path
        os.environ.clear()
        os.environ.update(self.environment)
        self.temporary.cleanup()
