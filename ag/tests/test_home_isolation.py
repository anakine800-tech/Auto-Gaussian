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


def test_default_global_registry_uses_isolated_home(isolated_test_home, tmp_path):
    from ag import _autonomy_store as disk
    from ag import autonomy_submission
    with autonomy_submission.machine_lock():
        with disk.manual_writers('a' * 64, create=True):
            pass
    assert (isolated_test_home / '.config/ag/autonomy-submit.lock').is_file()
    assert (isolated_test_home / '.config/ag/manual-writers' / ('a' * 64)).is_dir()
    assert not isolated_test_home.is_relative_to(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_previous_test_registry_does_not_survive(isolated_test_home):
    assert list(isolated_test_home.iterdir()) == []


def test_os_capabilities_and_function_identity_restore(tmp_path):
    from _test_home_isolation import HomeGuard
    names = ('stat', 'lstat', 'readlink', 'access', 'open', 'scandir', 'read', 'write', 'fstat')
    capabilities = ('supports_dir_fd', 'supports_fd', 'supports_follow_symlinks', 'supports_effective_ids')
    functions = {name: getattr(os, name) for name in names}
    supported = {name: getattr(os, name) for name in capabilities}
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    guard = HomeGuard([str(fake)])
    try:
        guard.install()
        for name, original in functions.items():
            wrapped = getattr(os, name)
            assert wrapped is not original
            for capability, members in supported.items():
                assert (wrapped in getattr(os, capability)) == (original in members), (name, capability)
    finally:
        guard.close()
    assert all(getattr(os, name) is original for name, original in functions.items())
    assert all(getattr(os, name) is original for name, original in supported.items())


def test_source_and_runtime_exceptions_are_read_only(tmp_path, home_guard):
    # A fake checkout demonstrates that no untracked study/config is exempted.
    from _test_home_isolation import HomeGuard
    fake = tmp_path / 'simulated-real-home'
    source = fake / 'repo/ag/src/example.py'
    source.parent.mkdir(parents=True)
    source.write_text('pass\n')
    runtime_data = fake / 'runtime/share/RDKit/Data'
    runtime_data.mkdir(parents=True)
    descriptor = runtime_data / 'FragmentDescriptors.csv'
    descriptor.write_text('synthetic dependency data\n')
    guard = HomeGuard([str(fake)], [str(source)], [str(runtime_data)], repo=str(fake / 'repo'))
    guard.active = True
    guard.check(source)
    guard.check(descriptor)
    for path, mode in ((source, 'write'), (descriptor, 'write'), (fake, 'list'),
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
        'from _pytest._code.code import Code\n'
        'before = dict(os.environ)\n'
        'source_properties = (Code.path, Code.fullsource)\n'
        f'result = pytest.main(["-c", {str(repo / "ag/pyproject.toml")!r}, {relative + "/test_home_isolation.py"!r}, '
        '"-k", "test_default_home_and_default_config", "-q"])\n'
        'assert result == 0\n'
        'assert dict(os.environ) == before\n'
        'assert (Code.path, Code.fullsource) == source_properties\n'
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


@pytest.mark.parametrize('filename', ['<frozen genericpath>', '<string>', '<stdin>'])
def test_virtual_traceback_sources_do_not_probe_disk(monkeypatch, filename):
    import inspect
    from _pytest._code.code import Code

    code = Code(compile('pass', filename, 'exec'))
    calls = []

    def unexpected_probe(*args, **kwargs):
        calls.append(args)
        raise HomeAccessError('virtual source reached disk/source lookup')

    with monkeypatch.context() as patch:
        patch.setattr(os, 'stat', unexpected_probe)
        patch.setattr(inspect, 'findsource', unexpected_probe)
        assert code.path == filename
        assert code.fullsource is None
    assert calls == []


def test_real_source_with_virtual_basename_still_protected(tmp_path, home_guard):
    from _pytest._code.code import Code

    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    source = fake / '<frozen genericpath>'
    source.write_bytes(b'pass\n')
    code = Code(compile('pass', str(source), 'exec'))
    with home_guard.protect_synthetic_home(fake):
        with pytest.raises(HomeAccessError):
            _ = code.path
        with pytest.raises(HomeAccessError):
            _ = code.fullsource
        with pytest.raises(HomeAccessError):
            source.read_bytes()
    assert list(fake.iterdir()) == [source]
    assert source.read_bytes() == b'pass\n'


def test_default_pytest_traceback_preserves_frozen_home_violation(tmp_path, home_guard):
    fake = tmp_path / 'simulated-real-home'
    fake.mkdir()
    sentinel = fake / 'sentinel'
    sentinel.write_bytes(b'unchanged')
    before = sentinel.stat()
    suite = tmp_path / 'suite'
    suite.mkdir()
    (suite / 'conftest.py').write_text(
        'from pathlib import Path\n'
        'import _test_home_pytest as isolation\n'
        f'isolation.start_session(Path({home_guard.repo!r}))\n'
        'pytest_plugins = ["_test_home_pytest"]\n'
    )
    test = suite / 'test_frozen_violation.py'
    test.write_text(
        'import os\n'
        'exec(compile("def frozen_probe(path):\\n    return os.path.exists(path)\\n", '
        '"<frozen genericpath>", "exec"))\n'
        'def test_original_home_violation():\n'
        '    try:\n'
        f'        frozen_probe({str(sentinel)!r})\n'
        '    except Exception:\n'
        '        pass\n'
    )
    config = suite / 'pytest.ini'
    config.write_text('[pytest]\n')
    with home_guard.protect_synthetic_home(fake):
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '-c', str(config), str(test), '-q'],
            cwd=home_guard.repo, env=dict(os.environ, PYTEST_ADDOPTS=''),
            capture_output=True, text=True,
        )
    output = result.stdout + result.stderr
    (suite / 'pytest.log').write_text(output)
    assert result.returncode == 1, output
    assert '1 failed' in output and 'INTERNALERROR' not in output
    assert '<frozen genericpath>' in output
    assert 'HomeAccessError: test HOME isolation blocked metadata: <protected-home>/sentinel' in output
    assert list(fake.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b'unchanged'
    assert sentinel.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize('prefix_name', ['prefix', 'base_prefix'])
def test_installed_timezone_data_is_read_only_and_overrides_stay_blocked(tmp_path, monkeypatch, prefix_name):
    import struct
    import zoneinfo
    from datetime import datetime, timedelta
    from _test_home_isolation import HomeGuard, runtime_trees

    fake = tmp_path / 'simulated-real-home'
    prefixes = {name: fake / name for name in ('prefix', 'base_prefix')}
    # A minimal v1 TZif file: one fixed offset, no transitions or leap seconds.
    tzif = (b'TZif\0' + bytes(15) + struct.pack('>6l', 0, 0, 0, 0, 1, 4)
            + struct.pack('>lbb', 28800, 0, 0) + b'SYN\0')
    for prefix in prefixes.values():
        path = prefix / 'share/zoneinfo/Asia/Shanghai'
        path.parent.mkdir(parents=True)
        path.write_bytes(tzif)
    private = fake / 'private-timezones'
    (private / 'Asia').mkdir(parents=True)
    (private / 'Asia/Shanghai').write_bytes(tzif)
    installed = prefixes[prefix_name] / 'share/zoneinfo'
    (installed / 'escape').symlink_to(private / 'Asia/Shanghai')
    for name, prefix in prefixes.items():
        monkeypatch.setattr(sys, name, str(prefix))
    monkeypatch.setenv('PYTHONTZPATH', str(private))
    monkeypatch.setenv('TZDIR', str(private))
    before = sorted(str(path.relative_to(fake)) for path in fake.rglob('*'))
    previous_tzpath = zoneinfo.TZPATH
    guard = HomeGuard([str(fake)], trees=runtime_trees())
    try:
        guard.install()
        zoneinfo.reset_tzpath([str(installed)])
        assert datetime(2026, 1, 1, tzinfo=zoneinfo.ZoneInfo.no_cache('Asia/Shanghai')).utcoffset() == timedelta(hours=8)
        for operation in (
            lambda: (installed / 'Asia/Shanghai').write_bytes(b'forbidden'),
            lambda: (installed / 'new-zone').write_bytes(b'forbidden'),
            lambda: (private / 'Asia/Shanghai').read_bytes(),
            lambda: (installed / 'escape').read_bytes(),
            lambda: (prefixes[prefix_name] / 'share/private-data').stat(),
        ):
            with pytest.raises(HomeAccessError):
                operation()
        zoneinfo.reset_tzpath()  # PYTHONTZPATH must not acquire a runtime exception.
        with pytest.raises(HomeAccessError):
            zoneinfo.ZoneInfo.no_cache('Asia/Shanghai')
    finally:
        guard.close()
        zoneinfo.reset_tzpath(previous_tzpath)
    assert sorted(str(path.relative_to(fake)) for path in fake.rglob('*')) == before
    assert (installed / 'Asia/Shanghai').read_bytes() == tzif
    assert (private / 'Asia/Shanghai').read_bytes() == tzif


def test_real_zoneinfo_data_read_under_home_guard(home_guard):
    import zoneinfo
    from datetime import datetime, timedelta

    assert home_guard.active
    zone = zoneinfo.ZoneInfo.no_cache('Asia/Shanghai')
    assert datetime(2026, 1, 1, tzinfo=zone).utcoffset() == timedelta(hours=8)
