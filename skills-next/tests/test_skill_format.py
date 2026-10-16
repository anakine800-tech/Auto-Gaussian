"""Maintained Skill publishing checks: discovery, usable links, complete cards and no private data.

The maintained entrypoints use two plain-scalar YAML fields. Check that small
subset without adding a YAML dependency to ag.
"""

from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = tuple(ROOT / f"auto-g16-{name}" for name in (
    "study", "recipes", "literature", "structures",
    "chemdraw-structures", "gaussian-learning-library",
))
CARDS = (
    "opt-freq", "sp", "rdkit-screen", "crest-screen", "thermo", "failure-diagnosis",
    "reaction-plan", "ts", "irc", "profile", "complex",
    "kinetics",
)
SECTIONS = (
    "适用范围", "前置条件", "输入模板", "资源建议", "提交前检查清单",
    "结果判据清单", "常见失败与处理", "常见坑",
)
OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
PRIVATE_PATTERNS = {
    "IPv4 address": re.compile(r"(?<![\w.])" + OCTET + r"(?:\." + OCTET + r"){3}(?![\w.])"),
    "user directory": re.compile(r"/(home|Users)/[A-Za-z0-9_.-]+"),
}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skill_frontmatter(skill):
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
    assert match, f"Missing YAML header: {skill.name}"
    lines = match.group(1).splitlines()
    assert len(lines) == 2, f"Expected name and description block fields: {skill.name}"
    name = re.fullmatch(r"name: ([a-z][a-z0-9-]*)", lines[0])
    description = re.fullmatch(r"description: (\w[^\n]*)", lines[1])
    assert name and name.group(1) == skill.name
    assert description, f"Missing plain-text description: {skill.name}"
    assert ": " not in description.group(1) and " #" not in description.group(1)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_relative_links_exist(skill):
    for path in skill.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        # Inline Markdown links and reference-link definitions used by Skills.
        targets = re.findall(r"\[[^\]\n]*\]\(([^\s)]+)\)", text)
        targets += re.findall(r"(?m)^\[[^\]\n]+\]:\s+(\S+)", text)
        for target in targets:
            url = urlsplit(target.strip("<>"))
            if url.scheme or url.netloc or not url.path:
                continue
            destination = Path(unquote(url.path))
            assert not destination.is_absolute(), f"Nonportable link in {path.name}"
            assert (path.parent / destination).is_file(), f"Broken link in {path.name}: {target}"


@pytest.mark.parametrize("card", CARDS)
def test_card_has_eight_sections(card):
    path = ROOT / "auto-g16-recipes" / "cards" / f"{card}.md"
    text = path.read_text(encoding="utf-8")
    headings = re.findall(r"(?m)^## (.+)$", text)
    assert headings == [f"{i}. {name}" for i, name in enumerate(SECTIONS, 1)]
    bodies = re.split(r"(?m)^## .+$", text)[1:]
    assert all(body.strip() for body in bodies), f"Empty section: {card}"


def test_files_have_no_private_addresses_or_user_paths():
    paths = [Path(__file__)]
    for skill in SKILLS:
        paths.extend(
            path for path in skill.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
    for path in paths:
        text = path.read_bytes().decode("utf-8", errors="replace")
        for label, pattern in PRIVATE_PATTERNS.items():
            # Do not echo a matched sensitive value into CI logs.
            assert not pattern.search(text), f"{label} in {path.name}"


# T17 baseline at main 6525b43: profile.md was the longest card, 190 lines.
# Fixed at 1.5 * 190 = 285; do not recompute from today's cards and let it drift.
MAX_CARD_LINES = 285
MAX_PITFALLS = 10


def check_card_size(text):
    # Bound accumulated advice so actionable criteria do not get buried.
    assert len(text.splitlines()) <= MAX_CARD_LINES, '卡片超出 285 行：先合并或删除，再追加'
    section = re.search(r'^## 8\. 常见坑\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    assert section, 'Missing 常见坑 section'
    count = len(re.findall(r'^\s*(?:[-*+] |\d+[.)] )', section.group(1), re.M))
    assert count <= MAX_PITFALLS, '常见坑超过 10 条：先合并或删除，再追加'


@pytest.mark.parametrize('path', sorted((ROOT / 'auto-g16-recipes/cards').glob('*.md')), ids=lambda p: p.stem)
def test_card_size_limits(path):
    check_card_size(path.read_text(encoding='utf-8'))


def test_card_size_limits_reject_growth():
    ten = '## 8. 常见坑\n' + '- pitfall\n' * 10
    check_card_size(ten)
    with pytest.raises(AssertionError, match='先合并或删除，再追加'):
        check_card_size(ten + '- another\n')
    exactly = ten + '\n' * (MAX_CARD_LINES - len(ten.splitlines()))
    check_card_size(exactly)
    with pytest.raises(AssertionError, match='先合并或删除，再追加'):
        check_card_size(exactly + '\n')
