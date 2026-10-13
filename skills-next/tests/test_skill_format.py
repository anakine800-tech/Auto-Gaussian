"""T3 publishing checks: discovery, usable links, complete cards and no private data.

The three T3 entrypoints use JSON flow mappings, a valid YAML subset. Parsing
that subset with the standard library validates these headers without adding
a YAML dependency to ag or imposing a header style on the separate T4 skill.
"""

import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = tuple(ROOT / f"auto-g16-{name}" for name in ("study", "recipes", "literature"))
CARDS = ("opt-freq", "sp", "rdkit-screen", "crest-screen", "thermo", "failure-diagnosis")
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
    metadata = json.loads(match.group(1))  # YAML flow mapping authored as JSON.
    assert isinstance(metadata, dict)
    assert metadata.get("name") == skill.name
    assert isinstance(metadata.get("description"), str)
    assert metadata["description"].strip()


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
        paths.extend(path for path in skill.rglob("*") if path.is_file())
    for path in paths:
        text = path.read_bytes().decode("utf-8", errors="replace")
        for label, pattern in PRIVATE_PATTERNS.items():
            # Do not echo a matched sensitive value into CI logs.
            assert not pattern.search(text), f"{label} in {path.name}"
