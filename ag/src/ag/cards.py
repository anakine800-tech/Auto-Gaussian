"""Capture the actual local recipe and Git provenance before preparation."""
from pathlib import Path
import re
import subprocess


def directory():
    deployed = Path.home() / '.codex' / 'skills' / 'auto-g16-recipes'
    if deployed.exists():
        return deployed.resolve() / 'cards'
    return Path(__file__).resolve().parents[3] / 'skills-next' / 'auto-g16-recipes' / 'cards'


def criteria(content):
    match = re.search(r'^## 6\. 结果判据清单\s*\n(.*?)(?=^## |\Z)', content, re.M | re.S)
    if not match:
        raise ValueError('Card has no section 6 结果判据清单')
    items = []
    collecting = False
    for line in match.group(1).splitlines():
        item = re.match(r'^\s*(?:[-*+] |\d+[.)] )(?:\[[ xX]\] )?(.*)', line)
        if item:
            items.append(item.group(1).strip())
            collecting = True
        elif collecting and line[:1].isspace() and line.strip():
            items[-1] += ' ' + line.strip()
        else:
            collecting = False
    if not items or not all(items):
        raise ValueError('Card section 6 has no usable checklist items')
    return items


def snapshot(name):
    name = name.removesuffix('.md')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name):
        raise ValueError('Expected a recipe card name, not a path')
    path = directory() / f'{name}.md'
    content = path.read_text(encoding='utf-8')
    criteria(content)
    def git(*args):
        result = subprocess.run(['git', '-C', str(path.parent), *args],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise ValueError('Cannot record Skills Git provenance; use a Git checkout')
        return result.stdout.strip()
    commit = git('rev-parse', 'HEAD')
    # Repository-wide status includes staged, unstaged and untracked changes.
    dirty = bool(git('status', '--porcelain', '--untracked-files=normal'))
    return dict(name=name, git_commit=commit, dirty=dirty, content=content)


def label(manifest):
    card = manifest.get('card')
    if not card:
        return 'Card: 未记录'
    return f"Card: {card['name']} | Skills: {card['git_commit'][:7]}" + (' (dirty)' if card['dirty'] else '')
