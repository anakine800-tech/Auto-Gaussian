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


def check_card_sections(text, card):
    headings = re.findall(r"(?m)^## (.+)$", text)
    if "要点" in headings:
        # The optional overview must not hide duplicate or misplaced sections.
        assert headings[0] == "要点" and headings.count("要点") == 1
        overview = re.match(r"\A# [^\n]+\n[ \t\n]*## 要点\n(.*?)(?=^## )", text, re.M | re.S)
        assert overview, f"要点须紧接卡片标题：{card}"
        body = overview.group(1).strip()
        item = r"(?m)^(?:[-*+] |\d+[.)] )\S[^\n]*(?:\n[ \t]+\S[^\n]*)*"
        assert 3 <= len(re.findall(item, body)) <= 5, f"要点须为 3–5 条列表：{card}"
        assert not re.sub(item, "", body).strip(), f"要点须使用列表形式：{card}"
        headings = headings[1:]
    assert headings == [f"{i}. {name}" for i, name in enumerate(SECTIONS, 1)]
    bodies = re.split(r"(?m)^## .+$", text)[1:]
    assert all(body.strip() for body in bodies), f"Empty section: {card}"


@pytest.mark.parametrize("card", CARDS)
def test_card_has_eight_sections(card):
    path = ROOT / "auto-g16-recipes" / "cards" / f"{card}.md"
    text = path.read_text(encoding="utf-8")
    check_card_sections(text, card)


@pytest.mark.parametrize("overview", [
    "",
    "## 要点\n\n" + "- point\n" * 3 + "\n",
    "## 要点\n\n" + "- point\n" * 5 + "\n",
    "## 要点\n\n" + "* point\n  continuation\n\n" * 4,
    "## 要点\n\n1. first\n2. second\n3. third\n\n",
])
def test_card_sections_accept_optional_keypoints(overview):
    sections = "".join(f"## {i}. {name}\n\nbody\n\n" for i, name in enumerate(SECTIONS, 1))
    check_card_sections("# Card\n\n" + overview + sections, "synthetic")


@pytest.mark.parametrize("case", [
    "before-title", "after-preface", "after-first", "at-end", "duplicate",
    "empty", "two", "six", "plain-text", "mixed-text", "empty-item",
    "missing-numbered-section", "reordered-numbered-sections", "empty-numbered-section",
])
def test_card_sections_reject_invalid_keypoints(case):
    overview = "## 要点\n\n" + "- point\n" * 3 + "\n"
    sections = [f"## {i}. {name}\n\nbody\n\n" for i, name in enumerate(SECTIONS, 1)]
    prefix = "# Card\n\n"
    if case == "before-title":
        prefix = overview + prefix
        overview = ""
    elif case == "after-preface":
        prefix += "preface\n\n"
    elif case == "after-first":
        sections.insert(1, overview)
        overview = ""
    elif case == "at-end":
        sections.append(overview)
        overview = ""
    elif case == "duplicate":
        overview += overview
    elif case in {"empty", "two", "six"}:
        count = {"empty": 0, "two": 2, "six": 6}[case]
        overview = "## 要点\n\n" + "- point\n" * count + "\n"
    elif case == "plain-text":
        overview = "## 要点\n\nfirst\nsecond\nthird\n\n"
    elif case == "mixed-text":
        overview += "not a list item\n\n"
    elif case == "empty-item":
        overview += "- \n\n"
    elif case == "missing-numbered-section":
        sections.pop()
    elif case == "reordered-numbered-sections":
        sections[0], sections[1] = sections[1], sections[0]
    elif case == "empty-numbered-section":
        sections[0] = sections[0].replace("body", "")
    with pytest.raises(AssertionError):
        check_card_sections(prefix + overview + "".join(sections), "synthetic")


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
