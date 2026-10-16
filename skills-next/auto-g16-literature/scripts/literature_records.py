#!/usr/bin/env python3
"""Lightweight metadata records; no scientific acceptance or ag dependencies.

改编自 archive/skills/auto-g16-reaction-literature/scripts/literature_search.py:
DOI/title normalization, API parsing and merge logic only. No legacy contracts.
"""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import html
from http.client import HTTPException
import io
import json
import math
from pathlib import Path
import re
import sys
import unicodedata
from urllib import error, parse, request

# T59 literature-record.md (including author and record-number columns).
COLUMNS = (
    "记录编号", "DOI", "标题", "作者", "年份", "核实方式（出版商页面 / Crossref）、位置与日期",
    "与本课题关系", "证据级别", "关键信息及位置（正文或 SI 页码/图表/小节）", "方法摘要",
    "未核实项", "检索式与检索日期",
)
SIGNALS = ("Crossref update-to：更正/撤稿等更新待人工核对",
           "Crossref relation：版本/关联关系待人工核对",
           "OpenAlex is_retracted：撤稿标记")


def clean_text(value):
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", value)).split())


def normalize_title(value):
    return unicodedata.normalize("NFKC", clean_text(value)).casefold()


def title_key(value):
    # Retain punctuation: chemical names such as 1,2 and 12 must not collapse.
    return re.sub(r"[‐‑‒–—−]", "-", normalize_title(value))


def normalize_doi(value):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"\s+", "", value).lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:", "", value)
    return value if re.fullmatch(r"10\.\d{4,9}/[^\s?#]+", value) else ""


def year_value(value):
    return value if type(value) is int and 1000 <= value <= 9999 else None


def crossref_year(item):
    # Registration/creation date is not a publication year.
    for key in ("published-print", "published-online", "published", "issued"):
        date = item.get(key)
        parts = date.get("date-parts") if isinstance(date, dict) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = year_value(parts[0][0])
            if year:
                return year
    return None


def record(doi="", title="", authors=(), year=None, source="", signals=()):
    return {"doi": normalize_doi(doi), "title": clean_text(title),
            "authors": [clean_text(a) for a in authors],
            "year": year_value(year), "sources": [source] if source else [],
            "signals": list(signals)}


def normalize_crossref(payload):
    message = payload.get("message")
    if not isinstance(message, dict):
        raise ValueError("invalid Crossref response")
    items = message.get("items", [message])
    if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
        raise ValueError("invalid Crossref items")
    result = []
    for item in items:
        title = item.get("title", "")
        if isinstance(title, list):
            title = title[0] if title else ""
        authors = [" ".join(filter(None, (clean_text(a.get("given")), clean_text(a.get("family")))))
                   or clean_text(a.get("name")) if isinstance(a, dict) else ""
                   for a in item.get("author", [])]
        signals = [label for key, label in zip(("update-to", "relation"), SIGNALS)
                   if item.get(key)]
        result.append(record(item.get("DOI"), title, authors, crossref_year(item), "Crossref", signals))
    return result


def normalize_openalex(payload):
    items = payload.get("results")
    if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
        raise ValueError("invalid OpenAlex results")
    result = []
    for item in items:
        authors = [a["author"].get("display_name", "")
                   if isinstance(a, dict) and isinstance(a.get("author"), dict) else ""
                   for a in item.get("authorships", [])]
        result.append(record(item.get("doi"), item.get("display_name") or item.get("title"), authors,
                             item.get("publication_year"), "OpenAlex",
                             [SIGNALS[2]] if item.get("is_retracted") is True else []))
    return result


def merge_records(records):
    merged = {}
    for index, incoming in enumerate(records):
        r = copy.deepcopy(incoming)
        doi = normalize_doi(r.get("doi"))
        r["doi"] = doi
        title, year = title_key(r.get("title")), r.get("year")
        # Missing title/year gives insufficient evidence for title-based deduplication.
        key = ("doi", doi) if doi else ("title", title, year) if title and year else ("row", index)
        if key not in merged:
            merged[key] = r
            r["variants"] = []
        out = merged[key]
        variant = {k: r.get(k) for k in ("title", "authors", "year")}
        if variant not in out["variants"]:
            out["variants"].append(variant)
        for field in ("title", "authors", "year"):
            if not out.get(field):
                out[field] = r.get(field)
        for field in ("sources", "signals"):
            out[field] = list(dict.fromkeys(out.get(field, []) + r.get(field, [])))
    return list(merged.values())


def crossref_url(doi, mailto):
    doi = normalize_doi(doi)
    if not doi:
        raise ValueError("invalid DOI")
    return "https://api.crossref.org/works/" + parse.quote(doi, safe="") + "?" + parse.urlencode({"mailto": mailto})


class NoRedirect(request.HTTPRedirectHandler):
    # Avoid following publisher URLs and forwarding contact parameters off API.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise error.URLError("API redirect refused")


def fetch_json(url, timeout):
    parts = parse.urlsplit(url)
    if parts.scheme != "https" or parts.netloc not in ("api.crossref.org", "api.openalex.org"):
        raise ValueError("only public metadata APIs are allowed")
    req = request.Request(url, headers={"Accept": "application/json", "User-Agent": "ag-literature-records/1"})
    with request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
        raw = response.read(25 * 1024 * 1024 + 1)
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError("API response exceeds 25 MiB")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("API response must be an object")
    return payload


def compare_record(expected, actual):
    mismatches = []
    for field in ("title", "authors", "year"):
        a, b = expected.get(field), actual.get(field)
        if field == "authors":
            a, b = (a[0] if a else ""), (b[0] if b else "")
        if field != "year":
            a, b = title_key(a), title_key(b)
        if not a or not b or a != b:
            mismatches.append(field)
    return mismatches


def verify_records(records, *, mailto="", timeout=20, offline=False, cache=None, fetcher=fetch_json):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if not offline and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", mailto):
        raise ValueError("online verify requires --mailto with a contact email")
    results = copy.deepcopy(records)
    for r in results:
        doi = normalize_doi(r.get("doi"))
        r["doi"] = doi
        r["verification"] = v = {"status": "unverified", "date": "", "method": "", "details": []}
        if not doi:
            v["details"] = ["无 DOI，待人工确认"]
            continue
        v.update(date=datetime.now(timezone.utc).date().isoformat(),
                 method="Crossref（离线缓存比对，非实时查询）" if offline else "Crossref")
        try:
            if offline:
                if cache is None or doi not in cache:
                    v.update(status="network_error", details=["offline_cache_missing；未查询，不能判为 not_found"])
                    continue
                payload = cache[doi]
                if payload == {"http_status": 404}:
                    v.update(status="not_found", details=["cached HTTP 404；非实时结果"])
                    continue
            else:
                payload = fetcher(crossref_url(doi, mailto), timeout)
            if not isinstance(payload, dict) or not isinstance(payload.get("message"), dict) or "items" in payload["message"]:
                raise ValueError("expected Crossref single-work response")
            actual = normalize_crossref(payload)[0]
            r["signals"] = list(dict.fromkeys(r.get("signals", []) + actual["signals"]))
            v["observed"] = {k: actual[k] for k in ("doi", "title", "authors", "year")}
            mismatch = ["doi"] if actual["doi"] != doi else []
            for variant in [r] + r.get("variants", []):
                mismatch.extend(compare_record(variant, actual))
            v.update(status="mismatch" if mismatch else "verified", details=sorted(set(mismatch)))
        except error.HTTPError as exc:
            v.update(status="not_found" if exc.code == 404 else "network_error",
                     details=["HTTP 429 rate_limited" if exc.code == 429 else f"HTTP {exc.code}"])
        except (error.URLError, OSError, HTTPException, ValueError, TypeError, KeyError, IndexError) as exc:
            # Never stringify exceptions: they may contain mailto, URLs or local paths.
            v.update(status="network_error", details=["timeout" if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
                                                       else "metadata_request_or_response_error"])
    return results


def export_rows(records):
    rows = []
    for r in records:
        v = r.get("verification", {})
        status = v.get("status", "unverified")
        verification = "；".join(filter(None, (v.get("method"), v.get("date"), status)))
        notes = list(r.get("signals", []))
        if not r.get("doi"):
            notes.append("无 DOI，待人工确认")
        if status != "verified":
            notes.extend(["未核实"] + v.get("details", []))
        # No extra columns: T59's unverified-items cell also carries update signals.
        rows.append(["", r.get("doi", ""), r.get("title", ""), "；".join(r.get("authors", [])),
                     r.get("year") or "", verification, "", "", "", "",
                     "；".join(dict.fromkeys(notes)), ""])
    return rows


def export_csv(records):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    # Prevent spreadsheet formula execution from external metadata.
    def cell(value):
        value = str(value)
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    writer.writerow(COLUMNS)
    writer.writerows([[cell(v) for v in row] for row in export_rows(records)])
    return stream.getvalue()


def export_markdown(records):
    def row(values):
        return "| " + " | ".join(html.escape(str(v)).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
                                  for v in values) + " |"
    return "\n".join([row(COLUMNS), row(["---"] * len(COLUMNS))] + [row(r) for r in export_rows(records)]) + "\n"


def normalize_input(path):
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not set(reader.fieldnames) & {"doi", "DOI", "title", "标题"}:
            raise ValueError("CSV requires doi/DOI or title/标题 header")
        result = []
        for row in reader:
            doi = row.get("doi") or row.get("DOI", "")
            if doi and not normalize_doi(doi):
                raise ValueError("invalid DOI in CSV")
            year = row.get("year") or row.get("年份")
            result.append(record(doi, normalize_title(row.get("title") or row.get("标题")),
                                 [row.get("first_author", "")], int(year) if year else None))
        return result
    result = []
    for line in filter(str.strip, text.splitlines()):
        doi = normalize_doi(line)
        if not doi and re.match(r"\s*(?:10\.|doi:|https?://(?:dx\.)?doi\.org/)", line, re.I):
            raise ValueError("invalid DOI in text input")
        result.append(record(doi, "" if doi else normalize_title(line)))
    return result


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_records(path):
    records = load_json(path)
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("expected a records JSON list")
    # Only script-owned fields are carried forward; raw API transport metadata is excluded.
    fields = ("doi", "title", "authors", "year", "sources", "signals", "variants", "verification")
    return [{k: r[k] for k in fields if k in r} for r in records]


def write_text(path, text):
    # A rerun must not erase a table already annotated by the researcher.
    with path.open("x", encoding="utf-8", newline="") as out:
        out.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("normalize", "merge", "verify", "export"):
        sub = commands.add_parser(name)
        sub.add_argument("inputs" if name == "merge" else "input", type=Path, **({"nargs": "+"} if name == "merge" else {}))
        sub.add_argument("--offline", action="store_true", help="no network; verify uses --cache only")
        if name == "export":
            sub.add_argument("--csv", type=Path, required=True)
            sub.add_argument("--markdown", type=Path, required=True)
        else:
            sub.add_argument("--output", type=Path, required=True)
        if name == "verify":
            sub.add_argument("--mailto", default="", help="contact email, never saved")
            sub.add_argument("--timeout", type=float, default=20)
            sub.add_argument("--cache", type=Path, help="offline JSON object: normalized DOI -> Crossref response or {http_status:404}")
    args = parser.parse_args(argv)
    try:
        if args.command == "normalize":
            records = normalize_input(args.input)
        elif args.command == "merge":
            records = []
            for path in args.inputs:
                payload = load_json(path)
                if not isinstance(payload, dict):
                    raise ValueError("expected an API response object")
                records.extend(normalize_openalex(payload) if "results" in payload else normalize_crossref(payload))
            records = merge_records(records)
        else:
            records = load_records(args.input)
        if args.command == "verify":
            if args.cache and not args.offline:
                raise ValueError("--cache requires --offline")
            cache = load_json(args.cache) if args.cache else None
            if cache is not None and not isinstance(cache, dict):
                raise ValueError("cache must be a DOI-keyed object")
            records = verify_records(records, mailto=args.mailto, timeout=args.timeout,
                                     offline=args.offline, cache=cache)
        if args.command == "export":
            if args.csv.resolve() == args.markdown.resolve() or args.csv.exists() or args.markdown.exists():
                raise ValueError("export requires two distinct new output files")
            write_text(args.csv, export_csv(records))
            write_text(args.markdown, export_markdown(records))
        else:
            write_text(args.output, json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        if args.command == "verify":
            counts = {s: sum(r["verification"]["status"] == s for r in records)
                      for s in ("verified", "mismatch", "not_found", "network_error", "unverified")}
            print(json.dumps(counts), file=sys.stderr)
            for index, r in enumerate(records, 1):
                v = r["verification"]
                if v["status"] != "verified":
                    print(f"record {index}: {v['status']}: " + "; ".join(v["details"]), file=sys.stderr)
            return 1 if any(r["verification"]["status"] != "verified" for r in records) else 0
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Error: invalid input/options or output unavailable; check format and use new output files.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
