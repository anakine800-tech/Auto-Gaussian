"""The only interactive confirmation implementation; no bypass switches."""
import subprocess
import sys

SCRIPT = '''on run argv
    set messageText to item 1 of argv
    set actionText to item 2 of argv
    set answer to display dialog messageText with title "ag" buttons {"取消", actionText} default button "取消" cancel button "取消" giving up after 300
    if gave up of answer then return "cancelled"
    if button returned of answer is actionText then return "confirmed"
    return "cancelled"
end run'''


def confirm(text, action='提交'):
    if sys.platform != 'darwin':
        return False
    if action not in ('提交', '取消作业'):
        raise ValueError('Unsupported confirmation action')
    try:
        p = subprocess.run(['osascript', '-e', SCRIPT, '--', text, action],
                           capture_output=True, text=True, timeout=310)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OSError('Confirmation dialog unavailable; stop') from exc
    if p.returncode:
        if '(-128)' in p.stderr:
            return False
        raise OSError('Could not obtain confirmation dialog result; stop')
    if p.stdout.strip() not in ('confirmed', 'cancelled'):
        raise OSError('Unexpected confirmation dialog result; stop')
    return p.stdout.strip() == 'confirmed'
