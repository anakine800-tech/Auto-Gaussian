"""Only inspect generated AppleScript and synthetic dialog results; never click."""
import subprocess

import pytest

from ag import cancel, confirm, state, submission, submit
from ag.transport import Result
from test_core import cfg, prepared, seed_submission, Fake
from test_slurm import multi, prepare


@pytest.mark.parametrize('action', ['提交', '取消作业'])
@pytest.mark.parametrize('response,code,stderr,expected', [
    ('confirmed\n', 0, '', True), ('cancelled\n', 0, '', False),
    ('', 1, 'User canceled. (-128)', False),
])
def test_labels_default_escape_and_timeout(monkeypatch, action, response, code, stderr, expected):
    monkeypatch.setattr(confirm.sys, 'platform', 'darwin')
    seen = []
    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return Result(code, response, stderr)
    monkeypatch.setattr(confirm.subprocess, 'run', run)
    message = 'Synthetic prompt " & do shell script "injection"'
    assert confirm.confirm(message, action) is expected
    (argv, kwargs), = seen
    assert argv == ['osascript', '-e', confirm.SCRIPT, '--', message, action]
    assert message not in confirm.SCRIPT
    assert kwargs == dict(capture_output=True, text=True, timeout=310)
    cancel_script, submit_script = confirm.SCRIPT.split('    else\n')
    assert 'if actionText is "取消作业" then' in cancel_script
    assert 'set actionText to "终止作业"' in cancel_script
    assert 'buttons {"保留作业", actionText} default button "保留作业" cancel button "保留作业" with icon caution giving up after 300' in cancel_script
    assert 'buttons {"不提交", actionText} default button "不提交" cancel button "不提交" giving up after 300' in submit_script
    assert 'with icon caution' not in submit_script
    assert 'if gave up of answer then return "cancelled"' in submit_script


@pytest.mark.parametrize('platform', ['darwin', 'linux'])
@pytest.mark.parametrize('action', ['终止作业', '保留作业', '不提交', 'other', ''])
def test_only_original_two_actions_are_accepted(monkeypatch, platform, action):
    monkeypatch.setattr(confirm.sys, 'platform', platform)
    monkeypatch.setattr(confirm.subprocess, 'run', lambda *a, **k: pytest.fail('must not launch'))
    with pytest.raises(ValueError, match='Unsupported'):
        confirm.confirm('synthetic', action)


@pytest.mark.parametrize('failure', ['timeout', 'start', 'result', 'exit'])
def test_dialog_errors_never_confirm(monkeypatch, failure):
    monkeypatch.setattr(confirm.sys, 'platform', 'darwin')
    def run(*args, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired('osascript', 310)
        if failure == 'start':
            raise OSError('synthetic')
        return Result(1 if failure == 'exit' else 0, 'unexpected')
    monkeypatch.setattr(confirm.subprocess, 'run', run)
    with pytest.raises(OSError):
        confirm.confirm('synthetic', '取消作业')


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
def test_cancel_prompt_identifies_exact_qualified_job(cfg, multi, prepared, tmp_path, monkeypatch, scheduler):
    if scheduler == 'pbs':
        selected, (path, manifest), job = cfg, prepared, 'default:123.fixture'
        state.write(path, 'submitting')
        seed_submission(path)
    else:
        selected = multi
        path, manifest = prepare(multi, tmp_path)
        job = 'batch:123'
        state.write(path, 'submitting')
        submission.record(path, manifest, '123')
        state.write(path, 'submitted', job_id=job)
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda text, action: seen.append((text, action)) or False)
    fake = Fake(cfg) if scheduler == 'pbs' else type('Inert', (), {})()
    with pytest.raises(submit.UserCancelled):
        cancel.cancel(selected, path, fake)
    text, action = seen[0]
    assert action == '取消作业'
    assert text.splitlines()[-1] == (f'点「终止作业」将停止 {job}，不会自动重提；'
                                   '点「保留作业」或按回车保持运行。')
    assert not (path / '.cancel-claim').exists()
    assert state.read(path)['state'] == 'submitted'
