#!/usr/bin/env python3
"""Search the portable Gaussian learning references without dependencies."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Hit:
    path: str
    heading: str
    line: int
    score: int
    excerpt: str


def query_terms(query: str) -> list[str]:
    normalized = query.casefold().strip()
    terms = [normalized] if normalized else []
    tokens = re.findall(r"[a-z0-9][a-z0-9_+./()=-]*|[\u3400-\u9fff]+", normalized)
    for token in tokens:
        if token not in terms:
            terms.append(token)
        if re.fullmatch(r"[\u3400-\u9fff]{4,}", token):
            for index in range(len(token) - 1):
                pair = token[index : index + 2]
                if pair not in terms:
                    terms.append(pair)
    return terms


def markdown_chunks(path: Path) -> Iterable[tuple[str, int, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    heading = path.stem
    start = 1
    body: list[str] = []
    for number, line in enumerate(lines, start=1):
        if re.match(r"^#{1,6}\s+", line):
            if body:
                yield heading, start, "\n".join(body)
            heading = re.sub(r"^#{1,6}\s+", "", line).strip()
            start = number
            body = [line]
        else:
            body.append(line)
    if body:
        yield heading, start, "\n".join(body)


def score_text(query: str, terms: list[str], heading: str, body: str) -> int:
    haystack = f"{heading}\n{body}".casefold()
    score = 30 if query.casefold() in haystack else 0
    heading_folded = heading.casefold()
    for term in terms[1:]:
        if term in haystack:
            score += 2
        if term in heading_folded:
            score += 3
    return score


def make_excerpt(body: str, terms: list[str], limit: int = 800) -> str:
    compact = re.sub(r"\n{3,}", "\n\n", body).strip()
    folded = compact.casefold()
    positions = [folded.find(term) for term in terms if term and folded.find(term) >= 0]
    start = max(0, min(positions) - 160) if positions else 0
    excerpt = compact[start : start + limit]
    if start:
        excerpt = "…" + excerpt
    if start + limit < len(compact):
        excerpt += "…"
    return excerpt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Words or an exact phrase to find")
    parser.add_argument("--root", type=Path, help="Custom Markdown directory")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    root = (args.root or skill_root / "references").resolve()
    if not root.is_dir():
        parser.error(f"search directory does not exist: {root}")

    terms = query_terms(args.query)
    hits: list[Hit] = []
    for path in sorted(root.rglob("*.md")):
        for heading, line, body in markdown_chunks(path):
            score = score_text(args.query, terms, heading, body)
            if not score:
                continue
            try:
                relative = path.relative_to(skill_root)
            except ValueError:
                relative = path
            hits.append(Hit(str(relative), heading, line, score, make_excerpt(body, terms)))

    hits.sort(key=lambda item: (-item.score, item.path, item.line))
    hits = hits[: max(args.max_results, 0)]
    if args.format == "json":
        print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
    elif not hits:
        print("No matching knowledge was found.")
    else:
        for hit in hits:
            print(f"{hit.path}:{hit.line} [{hit.score}] {hit.heading}")
            print(hit.excerpt)
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
