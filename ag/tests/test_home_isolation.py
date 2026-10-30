"""T211 negative probes use disposable simulated homes, never user data."""
import builtins
import io
import os
from pathlib import Path
import subprocess
import sys

import pytest

from _test_home_isolation import HomeAccessError


def test_default_home_and_default_config(isolated_test_home):
    from ag import config
    assert Path.home() == isolated_test_home == Path(os.environ['HOME'])
    assert Path('~/.config/ag').expanduser() == isolated_test_home / '.config/ag'
    assert os.path.expanduser('~/marker') == str(isolated_test_home / 'marker')
    with pytest.raises(config.ConfigError, match='Missing or invalid local configuration'):
        config.load_config()


@pytest.mark.parametrize('operation', [
    lambda p: builtins.open(p / 'sentinel'),
    lambda p: io.open(p / 'sentinel'),
    lambda p: (p / 'sentinel').read_bytes(),
    lambda p: (p / 'new-lock').write_text('forbidden'),
    lambda p: os.open(p / 'new-lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
    lambda p: list(p.iterdir()),
    lambda p: os.listdir(p),
    lambda p: os.scandir(p),
    lambda p: (p / 'registry').mkdir(),
    lambda p: (p / 'sentinel').stat(),
    lambda p: os.access(p / 'sentinel', os.R_OK),
    lambda p: (p / 'sentinel').unlink(),
    lambda p: (p / 'sentinel').rename(p / 'moved'),
    lambda p: (p / 'sentinel').chmod(0o600),
    lambda p: os.chdir(p),
], ids=['builtin-open', 'io-open', 'path-read', 'path-write', 'exclusive-lock',
        'iterdir', 'listdir', 'scandir', 'mkdir', 'stat', 'access', 'unlink', 'rename', 'chmod', 'chdir'])
def test_old_absolute_paths_fail_before_access(tmp_path, home_guard, operation):
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    sentinel = fake / 'sentinel'
    sentinel.write_bytes(b'unchanged')
    before = sentinel.stat()
    with home_guard.protect_synthetic_home(fake):
        with pytest.raises(HomeAccessError):
            operation(fake)
    assert list(fake.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b'unchanged'
    assert sentinel.stat().st_mtime_ns == before.st_mtime_ns


def test_restoring_path_home_cannot_escape(tmp_path, monkeypatch, home_guard):
    from ag import config
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    with home_guard.protect_synthetic_home(fake):
        monkeypatch.setattr(Path, 'home', classmethod(lambda cls: fake))
        with pytest.raises(HomeAccessError):
            config.load_config()
    assert list(fake.iterdir()) == []


def test_descriptor_relative_and_symlink_access(tmp_path, home_guard):
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    sentinel = fake / 'sentinel'
    sentinel.write_bytes(b'unchanged')
    fd = os.open(fake, os.O_RDONLY | os.O_DIRECTORY)
    filefd = os.open(sentinel, os.O_RDONLY)
    link = tmp_path / 'alias'
    link.symlink_to(fake, target_is_directory=True)
    try:
        with home_guard.protect_synthetic_home(fake):
            for operation in (
                lambda: os.open('sentinel', os.O_RDONLY, dir_fd=fd),
                lambda: os.open('lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY, dir_fd=fd),
                lambda: os.mkdir('registry', dir_fd=fd),
                lambda: os.stat('sentinel', dir_fd=fd),
                lambda: os.unlink('sentinel', dir_fd=fd),
                lambda: os.listdir(fd),
                lambda: os.scandir(fd),
                lambda: os.read(filefd, 1),
                lambda: (link / 'sentinel').read_bytes(),
            ):
                with pytest.raises(HomeAccessError):
                    operation()
    finally:
        os.close(filefd)
        os.close(fd)
    assert list(fake.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b'unchanged'


@pytest.mark.parametrize('entry', ['code', 'script'])
@pytest.mark.parametrize('explicit_env', [False, True])
def test_python_children_keep_guard(tmp_path, home_guard, entry, explicit_env):
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    code = ('import os, pathlib, sys\n'
            'assert pathlib.Path.home() == pathlib.Path(os.environ["HOME"])\n'
            'pathlib.Path(sys.argv[1]).joinpath("forbidden-lock").write_text("bad")\n')
    if entry == 'code':
        argv = [sys.executable, '-c', code, str(fake)]
    else:
        script = tmp_path / 'probe.py'
        script.write_text(code)
        argv = [sys.executable, str(script), str(fake)]
    kwargs = {'env': {'PATH': os.environ['PATH']}} if explicit_env else {}
    with home_guard.protect_synthetic_home(fake):
        result = subprocess.run(argv, capture_output=True, text=True, **kwargs)
    assert result.returncode != 0
    assert 'HomeAccessError' in result.stderr, result.stderr
    assert list(fake.iterdir()) == []


@pytest.mark.parametrize('flags', [
    ['-I'], ['-E'], ['-S'], ['-Es'], ['-sE'], ['-BS'], ['-sI'],
    ['-W', 'ignore', '-S'], ['-X', 'dev', '-sE'],
])
def test_python_cannot_disable_child_bootstrap(flags):
    with pytest.raises(HomeAccessError, match='disables'):
        subprocess.run([sys.executable, *flags, '-c', 'raise AssertionError("launched")'])


def test_default_global_registry_uses_isolated_home(isolated_test_home):
    from ag import _autonomy_store as disk
    from ag import autonomy_submission
    with autonomy_submission.machine_lock():
        with disk.manual_writers('a' * 64, create=True):
            pass
    assert (isolated_test_home / '.config/ag/autonomy-submit.lock').is_file()
    assert (isolated_test_home / '.config/ag/manual-writers' / ('a' * 64)).is_dir()


def test_previous_test_registry_does_not_survive(isolated_test_home):
    assert list(isolated_test_home.iterdir()) == []


def test_source_and_runtime_exceptions_are_read_only(tmp_path, home_guard):
    # A fake checkout demonstrates that no untracked study/config is exempted.
    from _test_home_isolation import HomeGuard
    fake = tmp_path / 'simulated-real-home'
    source = fake / 'repo/ag/src/example.py'
    source.parent.mkdir(parents=True)
    source.write_text('pass\n')
    guard = HomeGuard([str(fake)], [str(source)], repo=str(fake / 'repo'))
    guard.active = True
    guard.check(source)
    for path, mode in ((source, 'write'), (fake, 'list'),
                       (fake / 'repo/study/private.json', 'read'),
                       (fake / '.config/ag/config.toml', 'read')):
        with pytest.raises(HomeAccessError):
            guard.check(path, mode)


def test_child_crash_leaves_only_temporary_state(tmp_path, home_guard, isolated_test_home):
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    with home_guard.protect_synthetic_home(fake):
        result = subprocess.run([sys.executable, '-c',
            'import os; from pathlib import Path; '
            '(Path.home()/"crash-marker").write_text("temporary"); os._exit(7)'])
    assert result.returncode == 7
    assert (isolated_test_home / 'crash-marker').read_text() == 'temporary'
    assert list(fake.iterdir()) == []


def test_exception_recovery_cannot_hide_violation_from_pytest(tmp_path, home_guard):
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    suite = tmp_path / 'suite'
    suite.mkdir()
    test = suite / 'test_swallow.py'
    test.write_text(
        'from pathlib import Path\n'
        'def test_swallow():\n'
        '    try:\n'
        f'        Path({str(fake)!r}).joinpath("forbidden-lock").write_text("bad")\n'
        '    except Exception:\n'
        '        pass\n'
    )
    config = suite / 'pytest.ini'
    config.write_text('[pytest]\n')
    with home_guard.protect_synthetic_home(fake):
        result = subprocess.run([sys.executable, '-m', 'pytest', '-c', str(config), str(test), '-q', '--tb=short'],
                                cwd=suite, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert '1 failed' in result.stdout and 'HomeAccessError' in result.stdout
    assert list(fake.iterdir()) == []


@pytest.mark.parametrize('subdirectory', [False, True])
def test_pytest_entry_and_environment_restoration(home_guard, subdirectory):
    repo = Path(home_guard.repo)
    relative = 'tests' if subdirectory else 'ag/tests'
    code = (
        'import os, pytest\n'
        'before = dict(os.environ)\n'
        f'result = pytest.main(["-c", {str(repo / "ag/pyproject.toml")!r}, {relative + "/test_home_isolation.py"!r}, '
        '"-k", "test_default_home_and_default_config", "-q"])\n'
        'assert result == 0\n'
        'assert dict(os.environ) == before\n'
    )
    result = subprocess.run([sys.executable, '-c', code], cwd=repo / 'ag' if subdirectory else repo,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1 passed' in result.stdout


def test_symlink_then_parent_components_cannot_escape(tmp_path, home_guard):
    fake = tmp_path / 'simulated-real-home'
    (fake / 'child').mkdir(parents=True)
    (fake / 'sentinel').write_text('unchanged')
    link = tmp_path / 'alias'
    link.symlink_to(fake / 'child', target_is_directory=True)
    with home_guard.protect_synthetic_home(fake):
        with pytest.raises(HomeAccessError):
            open(str(link) + '/../sentinel')


def test_saved_directory_entry_and_open_stop_before_syscall(tmp_path, home_guard):
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    sentinel = fake / 'sentinel'
    sentinel.write_text('unchanged')
    saved_open = builtins.open
    with os.scandir(fake) as entries:
        entry = next(entries)
    later_audit_events = []
    watching = [True]

    def witness(event, args):
        if watching[0] and event == 'open' and args[0] == str(sentinel):
            later_audit_events.append(event)

    sys.addaudithook(witness)
    try:
        with home_guard.protect_synthetic_home(fake):
            with pytest.raises(HomeAccessError):
                saved_open(str(sentinel))
            for method in (entry.stat, entry.is_file, entry.is_dir, entry.is_symlink):
                with pytest.raises(HomeAccessError):
                    method()
    finally:
        watching[0] = False
    # An earlier audit hook raised: even the later hook, before the OS, was not called.
    assert later_audit_events == []
    assert sentinel.read_text() == 'unchanged'
