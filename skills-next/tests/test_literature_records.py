"""Synthetic metadata only. All network access is replaced, including CLI tests."""
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
from urllib import error, parse

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "auto-g16-literature/scripts/literature_records.py"
SPEC = importlib.util.spec_from_file_location("literature_records", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)
FIXTURES = Path(__file__).parent / "fixtures/literature"
DOI = "10.9999/synthetic-a"
CONTACT = "metadata@example.invalid"  # scan-public: allow synthetic reserved-domain email fixture


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("test attempted real network access")
    monkeypatch.setattr(mod.request.OpenerDirector, "open", blocked)
    monkeypatch.setattr(mod.request, "urlopen", blocked)


@pytest.fixture
def payload():
    raw = json.loads((FIXTURES / "crossref.json").read_text())
    return {"status": "ok", "query_date": "2001-02-03", "message": raw["message"]["items"][0]}


@pytest.fixture
def records(payload):
    return mod.normalize_crossref(payload)


@pytest.mark.parametrize("value", [DOI, DOI.upper(), " DOI: " + DOI.upper(),
                                    " https://doi.org/ " + DOI.upper() + " ", "http://dx.doi.org/" + DOI])
def test_doi_normalization(value):
    assert mod.normalize_doi(value) == DOI


@pytest.mark.parametrize("value", [None, "", "random title", "10.12/no", "https://untrusted.invalid/" + DOI])
def test_invalid_doi(value):
    assert not mod.normalize_doi(value)


def test_titles_and_publication_year():
    assert mod.normalize_title("  <i>Water</i> &amp; ＣＨＥＭＩＳＴＲＹ  ") == "water & chemistry"
    assert mod.title_key("1,2-water") != mod.title_key("12-water")
    assert mod.crossref_year({"created": {"date-parts": [[2025]]}}) is None
    assert mod.crossref_year({"issued": {"date-parts": [[True]]}}) is None


def test_merge_sources_and_signals():
    cr = mod.normalize_crossref(json.loads((FIXTURES / "crossref.json").read_text()))
    oa = mod.normalize_openalex(json.loads((FIXTURES / "openalex.json").read_text()))
    merged = mod.merge_records(cr + oa)
    assert len(merged) == 3
    assert merged[0]["sources"] == ["Crossref", "OpenAlex"]
    assert merged[0]["signals"] == list(mod.SIGNALS)
    assert merged[1]["sources"] == ["Crossref", "OpenAlex"]
    assert merged[2]["year"] == 2022
    assert "无 DOI，待人工确认" in mod.export_markdown(merged)
    assert len(mod.merge_records([mod.record(), mod.record()])) == 2
    assert len(mod.merge_records([mod.record(title="Same"), mod.record(title="same")])) == 2
    assert len(mod.merge_records([mod.record(DOI, "Same", year=2024), mod.record(title="same", year=2024)])) == 2


def test_verified_compares_and_keeps_observed(records, payload):
    calls = []
    def fetch(url, timeout):
        calls.append((url, timeout))
        return payload
    result = mod.verify_records(records, mailto=CONTACT, fetcher=fetch)
    v = result[0]["verification"]
    assert v["status"] == "verified"
    assert len(v["date"]) == 10
    assert v["observed"]["authors"] == ["Ada Example"]
    assert parse.parse_qs(parse.urlsplit(calls[0][0]).query)["mailto"] == [CONTACT]
    assert calls[0][1] == 20
    assert CONTACT not in json.dumps(result)
    assert "verification" not in records[0]


@pytest.mark.parametrize("field,value", [("title", "Different study"), ("authors", ["Bea Example"]),
                                          ("year", 2025), ("title", ""), ("authors", []), ("year", None)])
def test_mismatches_and_missing_fields(records, payload, field, value):
    records[0][field] = value
    result = mod.verify_records(records, offline=True, cache={DOI: payload})
    assert result[0]["verification"]["status"] == "mismatch"
    assert field in result[0]["verification"]["details"]


def test_doi_response_identity(records, payload):
    payload["message"]["DOI"] = "10.9999/another"
    v = mod.verify_records(records, offline=True, cache={DOI: payload})[0]["verification"]
    assert v["status"] == "mismatch" and "doi" in v["details"]


def test_merge_conflict_is_not_silently_verified(records, payload):
    other = copy.deepcopy(records[0])
    other["title"] = "A different synthetic study"
    merged = mod.merge_records(records + [other])
    assert len(merged) == 1 and len(merged[0]["variants"]) == 2
    assert mod.verify_records(merged, offline=True, cache={DOI: payload})[0]["verification"]["status"] == "mismatch"


@pytest.mark.parametrize("code,status", [(404, "not_found"), (429, "network_error"), (503, "network_error")])
def test_http_failures(records, code, status):
    def fetch(url, timeout):
        raise error.HTTPError(url, code, CONTACT, {}, None)
    result = mod.verify_records(records, mailto=CONTACT, fetcher=fetch)
    assert result[0]["verification"]["status"] == status
    assert str(code) in result[0]["verification"]["details"][0]
    assert CONTACT not in json.dumps(result)


@pytest.mark.parametrize("failure", [TimeoutError("private details"), error.URLError(CONTACT),
                                     ValueError(CONTACT), OSError("private path"),
                                     mod.HTTPException("private response")])
def test_network_failures_replace_stale_verified(records, failure):
    records[0]["verification"] = {"status": "verified", "date": "2000-01-01"}
    def fetch(url, timeout):
        raise failure
    result = mod.verify_records(records, mailto=CONTACT, fetcher=fetch)
    assert result[0]["verification"]["status"] == "network_error"
    assert CONTACT not in json.dumps(result)
    assert "private" not in json.dumps(result)
    assert "未核实" in mod.export_markdown(result)


def test_offline_absence_not_false_404(records, payload):
    assert mod.verify_records(records, offline=True)[0]["verification"]["status"] == "network_error"
    result = mod.verify_records(records, offline=True, cache={DOI: {"http_status": 404, "query_date": "2001-02-03"}})
    assert result[0]["verification"]["status"] == "not_found"
    result = mod.verify_records(records, offline=True, cache={DOI: payload})
    assert "非实时" in result[0]["verification"]["method"]
    assert mod.verify_records([mod.record(title="No DOI")], offline=True)[0]["verification"]["status"] == "unverified"


@pytest.mark.parametrize("bad_payload", [[], {}, {"message": {"items": []}}, {"message": {"author": None}}])
def test_bad_api_response(records, bad_payload):
    result = mod.verify_records(records, mailto=CONTACT, fetcher=lambda *args: bad_payload)
    assert result[0]["verification"]["status"] == "network_error"


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeouts(records, timeout):
    with pytest.raises(ValueError):
        mod.verify_records(records, offline=True, timeout=timeout)


def test_network_destination_and_redirect_guard():
    for url in ("https://publisher.invalid/work", "http://api.crossref.org/works", "https://api.crossref.org.evil.invalid/works"):
        with pytest.raises(ValueError):
            mod.fetch_json(url, 20)
    with pytest.raises(error.URLError):
        mod.NoRedirect().redirect_request(None, None, 302, "", {}, "https://publisher.invalid/")


def test_fetch_uses_timeout_and_no_redirect(monkeypatch, payload):
    captured = {}
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return json.dumps(payload).encode()
    class Opener:
        def open(self, req, timeout):
            captured.update(url=req.full_url, timeout=timeout)
            return Response()
    def build(handler):
        assert isinstance(handler, mod.NoRedirect)
        return Opener()
    monkeypatch.setattr(mod.request, "build_opener", build)
    assert mod.fetch_json(mod.crossref_url(DOI, CONTACT), 12) == payload
    assert captured["timeout"] == 12 and DOI in parse.unquote(captured["url"])


def test_export_headers_manual_cells_and_status(records, payload):
    result = mod.verify_records(records, offline=True, cache={DOI: payload})
    rows = list(csv.reader(io.StringIO(mod.export_csv(result))))
    assert rows[0] == list(mod.COLUMNS)
    assert len(rows[1]) == 12
    assert rows[1][6:10] == [""] * 4 and rows[1][11] == "" and rows[1][0] == ""
    assert rows[1][3] == "Ada Example"
    assert "verified" in rows[1][5]
    assert "update-to" in rows[1][10] and "relation" in rows[1][10]
    assert "verified" in mod.export_markdown(result)


def test_t59_columns_when_template_is_available():
    template = ROOT / "auto-g16-study/references/literature-record.md"
    if not template.exists():
        pytest.skip("T59 template not merged; columns aligned with its implementation draft")
    headers = next(line for line in template.read_text().splitlines() if line.startswith("| 记录编号 | DOI |"))
    assert [cell.strip() for cell in headers.strip("|").split("|")] == list(mod.COLUMNS)


def test_export_escapes_external_metadata():
    records = [mod.record(title='=formula | <img> & "quoted"')]
    csv_rows = list(csv.reader(io.StringIO(mod.export_csv(records))))
    assert csv_rows[1][2].startswith("'=formula")
    md = mod.export_markdown(records)
    assert "\\|" in md and "&amp;" in md and "<img>" not in md


def test_cli_normalize_text_csv_and_exclusive_output(tmp_path):
    txt = tmp_path / "input.txt"
    txt.write_text(" https://doi.org/10.9999/SYNTHETIC-A \n  Synthetic WATER  Study\n")
    out = tmp_path / "records.json"
    assert mod.main(["normalize", str(txt), "--offline", "--output", str(out)]) == 0
    records = json.loads(out.read_text())
    assert records[0]["doi"] == DOI and records[1]["title"] == "synthetic water study"
    before = out.read_bytes()
    assert mod.main(["normalize", str(txt), "--output", str(out)]) == 2
    assert out.read_bytes() == before
    inp = tmp_path / "input.csv"
    inp.write_text('doi,title,year,first_author\n10.9999/SYNTHETIC-A,"Synthetic, Water",2024,Ada Example\n')
    normalized = mod.normalize_input(inp)
    assert normalized[0]["title"] == "synthetic, water" and normalized[0]["year"] == 2024


def test_cli_merge_verify_export_pipeline(tmp_path, payload, capsys):
    merged, verified = tmp_path / "merged.json", tmp_path / "verified.json"
    cache, csv_file, md_file = tmp_path / "cache.json", tmp_path / "records.csv", tmp_path / "records.md"
    cache.write_text(json.dumps({DOI: payload}))
    assert mod.main(["merge", str(FIXTURES / "crossref.json"), str(FIXTURES / "openalex.json"),
                     "--offline", "--output", str(merged)]) == 0
    assert mod.main(["verify", str(merged), "--offline", "--cache", str(cache), "--output", str(verified)]) == 1
    statuses = [r["verification"]["status"] for r in json.loads(verified.read_text())]
    assert statuses == ["verified", "unverified", "unverified"]
    assert mod.main(["export", str(verified), "--csv", str(csv_file), "--markdown", str(md_file)]) == 0
    assert "is_retracted" in md_file.read_text()
    assert "unverified" in capsys.readouterr().err
    assert mod.main(["export", str(verified), "--csv", str(csv_file), "--markdown", str(md_file)]) == 2


def test_invalid_inputs_and_private_error_text(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    output = tmp_path / "out.json"
    assert mod.main(["merge", str(bad), "--output", str(output)]) == 2
    assert not output.exists()
    assert str(tmp_path) not in capsys.readouterr().err
    with pytest.raises(ValueError):
        mod.verify_records([], mailto="")


def test_missing_first_author_does_not_promote_second(records, payload):
    payload["message"]["author"] = [{}, {"given": "Ada", "family": "Example"}]
    normalized = mod.normalize_crossref(payload)
    assert normalized[0]["authors"] == ["", "Ada Example"]
    result = mod.verify_records(records, offline=True, cache={DOI: payload})
    assert result[0]["verification"]["status"] == "mismatch"
    assert "authors" in result[0]["verification"]["details"]
    oa = mod.normalize_openalex({"results": [{"authorships": [{}, {"author": {"display_name": "Ada Example"}}]}]})
    assert oa[0]["authors"] == ["", "Ada Example"]


def test_raw_transport_metadata_is_not_copied(payload):
    payload["mailto"] = CONTACT
    payload["api_key"] = "synthetic-secret"
    payload["message"]["URL"] = "https://publisher.invalid/?api_key=synthetic-secret"
    payload["message"]["local_path"] = "private-input-path"
    result = mod.normalize_crossref(payload)
    text = json.dumps(result) + mod.export_csv(result) + mod.export_markdown(result)
    assert CONTACT not in text and "synthetic-secret" not in text and "private-input-path" not in text


def test_title_only_csv_and_bad_doi(tmp_path):
    path = tmp_path / "titles.csv"
    path.write_text('标题\nSynthetic WATER\n')
    assert mod.normalize_input(path)[0]["title"] == "synthetic water"
    path.write_text('doi,title\nnot-a-doi,Synthetic WATER\n')
    with pytest.raises(ValueError):
        mod.normalize_input(path)


def test_same_export_paths_are_rejected(tmp_path, records):
    source, output = tmp_path / "records.json", tmp_path / "table.txt"
    source.write_text(json.dumps(records))
    assert mod.main(["export", str(source), "--csv", str(output), "--markdown", str(output)]) == 2
    assert not output.exists()


@pytest.mark.parametrize('query_date', [None, '', 'bad', '2001-02-30', 2001])
@pytest.mark.parametrize('not_found', [False, True])
def test_undated_cache_is_unverified(records, payload, query_date, not_found):
    cached = {"http_status": 404} if not_found else payload
    cached.pop("query_date", None)
    if query_date is not None:
        cached["query_date"] = query_date
    v = mod.verify_records(records, offline=True, cache={DOI: cached})[0]["verification"]
    assert v["status"] == "unverified" and v["date"] == ""
    assert "缓存" in v["method"]
    assert any("日期未知" in detail for detail in v["details"])


def test_offline_verification_keeps_query_date_in_exports(records, payload):
    result = mod.verify_records(records, offline=True, cache={DOI: payload})
    v = result[0]["verification"]
    assert v["status"] == "verified" and v["date"] == "2001-02-03"
    assert "缓存" in v["method"]
    assert "2001-02-03" in mod.export_csv(result)
    assert "2001-02-03" in mod.export_markdown(result)
    missing = mod.verify_records(records, offline=True)[0]["verification"]
    assert missing["date"] == "" and missing["status"] == "network_error"
