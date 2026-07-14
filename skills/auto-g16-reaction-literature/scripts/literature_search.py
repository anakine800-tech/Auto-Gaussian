#!/usr/bin/env python3
"""Reproducible discovery and review scaffolding for mechanism/TS literature."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


INTAKE_SCHEMA = "gaussian-reaction-literature-request/1"
PLAN_SCHEMA = "gaussian-reaction-literature-query/1"
RETRIEVAL_SCHEMA = "gaussian-reaction-literature-retrieval/1"
LEDGER_SCHEMA = "gaussian-reaction-literature-candidate-ledger/1"
REVIEW_SCHEMA = "gaussian-reaction-literature-evidence/1"

ALLOWED_TARGETS = {
    "proposed_mechanism",
    "alternative_pathway",
    "active_catalyst_state",
    "elementary_step",
    "transition_state_model",
    "computational_protocol",
    "barrier_or_energy_profile",
    "normal_mode",
    "irc",
    "selectivity_model",
    "coordinates",
}

EVIDENCE_WORDS = (
    "mechanism",
    "mechanistic",
    "transition state",
    "transition-state",
    "density functional",
    "dft",
    "computational",
    "activation barrier",
    "free energy profile",
    "intrinsic reaction coordinate",
    "irc",
    "selectivity",
)


def die(message: str) -> "NoReturn":
    raise SystemExit(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_payload_hash(payload: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(payload)
    result.pop(field, None)
    result[field] = hashlib.sha256(canonical_bytes(result)).hexdigest()
    return result


def verify_payload_hash(payload: dict[str, Any], field: str) -> None:
    expected = payload.get(field)
    if not expected:
        die(f"missing {field}")
    check = dict(payload)
    check.pop(field, None)
    actual = hashlib.sha256(canonical_bytes(check)).hexdigest()
    if actual != expected:
        die(f"{field} mismatch: artifact was modified after hashing")


def reject_constant(value: str) -> "NoReturn":
    die(f"non-standard JSON numeric constant is forbidden: {value}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            die(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        die(f"cannot read JSON {path}: {exc}")
    if not isinstance(value, dict):
        die(f"expected a JSON object in {path}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        die(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, content: str) -> None:
    if path.exists():
        die(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        die(f"{label} must be a list of non-empty strings")
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        cleaned = " ".join(item.split())
        key = cleaned.casefold()
        if key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def validate_intake(intake: dict[str, Any]) -> dict[str, Any]:
    if intake.get("schema") != INTAKE_SCHEMA:
        die(f"intake schema must be {INTAKE_SCHEMA}")
    request_id = intake.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", request_id):
        die("request_id must contain only letters, digits, dot, underscore, or hyphen")
    question = intake.get("scientific_question")
    if not isinstance(question, str) or not question.strip():
        die("scientific_question is required")
    reaction = intake.get("reaction")
    if not isinstance(reaction, dict) or not isinstance(
        reaction.get("transformation_class"), str
    ) or not reaction["transformation_class"].strip():
        die("reaction.transformation_class is required and must be reviewed")
    terms = intake.get("search_terms")
    if not isinstance(terms, dict):
        die("search_terms object is required")
    normalized_terms = {
        key: string_list(terms.get(key), f"search_terms.{key}")
        for key in (
            "exact_phrases",
            "catalyst_terms",
            "substrate_terms",
            "transformation_terms",
            "mechanism_terms",
            "exclusions",
        )
    }
    if not normalized_terms["transformation_terms"]:
        die("at least one explicit search_terms.transformation_terms value is required")
    if not (
        normalized_terms["catalyst_terms"]
        or normalized_terms["substrate_terms"]
        or normalized_terms["exact_phrases"]
    ):
        die("provide a catalyst term, substrate term, or exact phrase")

    targets = string_list(intake.get("target_evidence"), "target_evidence")
    unknown = sorted(set(targets) - ALLOWED_TARGETS)
    if unknown:
        die(f"unsupported target_evidence values: {', '.join(unknown)}")
    if not targets:
        die("target_evidence must contain at least one evidence category")

    hypotheses = intake.get("mechanism_hypotheses", [])
    if not isinstance(hypotheses, list):
        die("mechanism_hypotheses must be a list")
    normalized_hypotheses: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            die(f"mechanism_hypotheses[{index}] must be an object")
        hypothesis_id = item.get("hypothesis_id")
        label = item.get("label")
        if not isinstance(hypothesis_id, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]+", hypothesis_id
        ):
            die(f"mechanism_hypotheses[{index}].hypothesis_id is invalid")
        if hypothesis_id in ids:
            die(f"duplicate hypothesis_id: {hypothesis_id}")
        if not isinstance(label, str) or not label.strip():
            die(f"mechanism_hypotheses[{index}].label is required")
        ids.add(hypothesis_id)
        normalized_hypotheses.append(
            {
                "hypothesis_id": hypothesis_id,
                "label": " ".join(label.split()),
                "keywords": string_list(item.get("keywords"), f"hypothesis {hypothesis_id} keywords"),
                "status": "unselected_hypothesis",
            }
        )

    citations = intake.get("known_citations", [])
    if not isinstance(citations, list):
        die("known_citations must be a list")
    normalized_citations: list[dict[str, str]] = []
    for index, item in enumerate(citations):
        if not isinstance(item, dict) or not isinstance(item.get("doi"), str):
            die(f"known_citations[{index}] must contain a DOI")
        doi = normalize_doi(item["doi"])
        if not doi:
            die(f"known_citations[{index}].doi is invalid")
        normalized_citations.append(
            {"doi": doi, "role": str(item.get("role") or "seed")}
        )

    years = intake.get("publication_years")
    normalized_years = None
    if years is not None:
        if not isinstance(years, dict):
            die("publication_years must be an object")
        start, end = years.get("from"), years.get("until")
        if not isinstance(start, int) or not isinstance(end, int) or not (1500 <= start <= end <= 2100):
            die("publication_years.from/until must be a valid inclusive range")
        normalized_years = {"from": start, "until": end}

    upstream = intake.get("upstream_artifacts", {})
    if not isinstance(upstream, dict):
        die("upstream_artifacts must be an object when supplied")
    normalized_upstream: dict[str, dict[str, str] | None] = {}
    for key in (
        "reaction_intake",
        "species_registry",
        "condition_model",
        "knowledge_snapshot",
    ):
        binding = upstream.get(key)
        if binding is None:
            normalized_upstream[key] = None
            continue
        if not isinstance(binding, dict) or any(
            not isinstance(binding.get(field), str) or not binding[field].strip()
            for field in ("path", "sha256", "schema", "payload_sha256")
        ):
            die(
                f"upstream_artifacts.{key} must be null or contain path, sha256, schema, and payload_sha256"
            )
        for field in ("sha256", "payload_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", binding[field]):
                die(f"upstream_artifacts.{key}.{field} must be lowercase SHA-256")
        normalized_upstream[key] = {
            field: binding[field]
            for field in ("path", "sha256", "schema", "payload_sha256")
        }

    return {
        "request_id": request_id,
        "scientific_question": question.strip(),
        "reaction": reaction,
        "search_terms": normalized_terms,
        "mechanism_hypotheses": normalized_hypotheses,
        "target_evidence": targets,
        "known_citations": normalized_citations,
        "publication_years": normalized_years,
        "upstream_artifacts": normalized_upstream,
        "review_status": intake.get("review_status"),
    }


def verify_upstream_bindings(
    bindings: dict[str, dict[str, str] | None], intake_path: Path
) -> None:
    for key, binding in bindings.items():
        if binding is None:
            continue
        direct = Path(binding["path"])
        candidates = [direct, intake_path.parent / direct]
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            die(f"upstream_artifacts.{key}.path does not resolve to a file")
        if source.is_symlink():
            die(f"upstream_artifacts.{key}.path must not be a symlink")
        if sha256_path(source) != binding["sha256"]:
            die(f"upstream_artifacts.{key}.sha256 mismatch")
        artifact = load_json(source)
        if artifact.get("schema") != binding["schema"]:
            die(f"upstream_artifacts.{key}.schema mismatch")
        payload_hashes = {
            value
            for field, value in artifact.items()
            if field.endswith("payload_sha256") and isinstance(value, str)
        }
        if binding["payload_sha256"] not in payload_hashes:
            die(f"upstream_artifacts.{key}.payload_sha256 mismatch")


def quote_term(term: str) -> str:
    cleaned = term.replace('"', " ")
    return f'"{cleaned}"' if " " in cleaned else cleaned


def command_plan(args: argparse.Namespace) -> None:
    intake_path = Path(args.intake)
    intake = load_json(intake_path)
    normalized = validate_intake(intake)
    verify_upstream_bindings(normalized["upstream_artifacts"], intake_path)
    terms = normalized["search_terms"]
    queries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_query(
        lane: str,
        pieces: list[str],
        rationale: str,
        expected: list[str],
        mode: str = "bibliographic",
    ) -> None:
        clean = [piece for piece in pieces if piece]
        text = " ".join(quote_term(piece) for piece in clean)
        text = " ".join(text.split())
        key = (mode, text.casefold())
        if not text or key in seen:
            return
        if len(text) > 350:
            die(f"generated query exceeds 350 characters: {text}")
        seen.add(key)
        queries.append(
            {
                "query_id": f"q{len(queries) + 1:03d}",
                "lane": lane,
                "mode": mode,
                "query_text": text,
                "rationale": rationale,
                "expected_evidence": expected,
                "sources": ["crossref", "openalex"],
            }
        )

    transformations = terms["transformation_terms"]
    catalysts = terms["catalyst_terms"]
    substrates = terms["substrate_terms"]
    mechanisms = terms["mechanism_terms"]
    target_evidence = normalized["target_evidence"]

    for phrase in terms["exact_phrases"][:3]:
        add_query(
            "exact_system",
            [phrase],
            "User-supplied exact phrase for high-precision discovery.",
            target_evidence,
        )
    for catalyst in catalysts[:2]:
        for transformation in transformations[:2]:
            add_query(
                "catalyst_transformation",
                [catalyst, transformation],
                "Preserve catalyst and transformation while relaxing exact substrates.",
                target_evidence,
            )
    for substrate in substrates[:2]:
        for transformation in transformations[:2]:
            add_query(
                "substrate_transformation",
                [substrate, transformation],
                "Preserve substrate and transformation while allowing catalyst analogies.",
                target_evidence,
            )
    for mechanism in mechanisms[:4]:
        add_query(
            "mechanism_hypothesis",
            [transformations[0], mechanism, "mechanism"],
            "Search an explicit, unselected mechanism term from the intake.",
            ["proposed_mechanism", "alternative_pathway", "elementary_step"],
        )
    for hypothesis in normalized["mechanism_hypotheses"][:4]:
        for keyword in hypothesis["keywords"][:2]:
            add_query(
                "mechanism_hypothesis",
                [transformations[0], keyword],
                f"Search explicit keywords for unselected hypothesis {hypothesis['hypothesis_id']}.",
                ["proposed_mechanism", "alternative_pathway", "elementary_step"],
            )

    ts_targets = {
        "transition_state_model",
        "computational_protocol",
        "barrier_or_energy_profile",
        "normal_mode",
        "irc",
        "selectivity_model",
        "coordinates",
    }
    if ts_targets.intersection(target_evidence):
        anchor = (catalysts or substrates or terms["exact_phrases"])[0]
        for evidence_word in ("transition state", "DFT", "activation barrier", "IRC"):
            add_query(
                "ts_computational",
                [transformations[0], anchor, evidence_word],
                "Add a generic computational-evidence term without selecting a method.",
                sorted(ts_targets.intersection(target_evidence)),
            )
        add_query(
            "elementary_step_analogy",
            [transformations[0], "transition state"],
            "Broaden to the transformation class; any result is analogy until reviewed.",
            sorted(ts_targets.intersection(target_evidence)),
        )
    add_query(
        "review_vocabulary",
        [transformations[0], "mechanism", "review"],
        "Find review vocabulary and seed citations; reviews are not candidate-specific evidence.",
        ["proposed_mechanism"],
    )
    for citation in normalized["known_citations"]:
        add_query(
            "seed_doi",
            [citation["doi"]],
            f"Retrieve user-supplied DOI seed ({citation['role']}).",
            target_evidence,
            mode="doi",
        )

    if not queries:
        die("intake did not produce any query")
    missing_upstream = [
        key
        for key, binding in normalized["upstream_artifacts"].items()
        if binding is None
    ]
    plan = {
        "schema": PLAN_SCHEMA,
        "request_id": normalized["request_id"],
        "created_at": utc_now(),
        "intake_artifact": {
            "path": str(intake_path),
            "sha256": sha256_path(intake_path),
        },
        "scientific_question": normalized["scientific_question"],
        "reaction_summary": {
            "transformation_class": normalized["reaction"]["transformation_class"],
            "unresolved": normalized["reaction"].get("unresolved", []),
        },
        "ranking_terms": terms,
        "mechanism_hypotheses": normalized["mechanism_hypotheses"],
        "target_evidence": target_evidence,
        "publication_years": normalized["publication_years"],
        "upstream_artifacts": normalized["upstream_artifacts"],
        "w2_binding_status": (
            "complete_for_search_scope_review"
            if not missing_upstream
            else "standalone_search_not_promotable"
        ),
        "promotion_blockers": [
            f"missing_upstream_binding:{key}" for key in missing_upstream
        ],
        "queries": queries,
        "query_count": len(queries),
        "limitations": [
            "Queries combine only reviewed intake terms and generic evidence words.",
            "No structure or substructure search is performed.",
            "A finite zero-result search does not prove absence of precedent.",
            "All returned records remain metadata-only candidates pending primary/SI review.",
        ],
        "calculation_ready": False,
        "promotable_to_mechanism_support": False,
        "promotable_to_ts_precedent_map": False,
        "no_submission_authorization": True,
    }
    plan = add_payload_hash(plan, "search_plan_payload_sha256")
    write_json(Path(args.output), plan)
    print(json.dumps({"output": args.output, "queries": len(queries)}, ensure_ascii=False))


def normalize_doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi if re.fullmatch(r"10\.\d{4,9}/\S+", doi) else None


def sanitized_url(url: str) -> str:
    parts = parse.urlsplit(url)
    query = [
        (key, value)
        for key, value in parse.parse_qsl(parts.query, keep_blank_values=True)
        if key not in {"mailto", "api_key"}
    ]
    return parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parse.urlencode(query), "")
    )


def crossref_url(query: dict[str, Any], rows: int, years: Any, mailto: str) -> str:
    if query["mode"] == "doi":
        base = "https://api.crossref.org/works/" + parse.quote(
            normalize_doi(query["query_text"]) or query["query_text"], safe=""
        )
        params: dict[str, str] = {"mailto": mailto}
    else:
        base = "https://api.crossref.org/works"
        params = {
            "query.bibliographic": query["query_text"],
            "rows": str(rows),
            "mailto": mailto,
        }
        if years:
            params["filter"] = (
                f"from-pub-date:{years['from']}-01-01,"
                f"until-pub-date:{years['until']}-12-31"
            )
    return base + "?" + parse.urlencode(params)


def openalex_url(query: dict[str, Any], rows: int, years: Any, api_key: str | None) -> str:
    params: dict[str, str] = {"per_page": str(rows)}
    if query["mode"] == "doi":
        doi = normalize_doi(query["query_text"])
        params["filter"] = f"doi:https://doi.org/{doi}"
    else:
        params["search"] = query["query_text"]
        if years:
            params["filter"] = (
                f"from_publication_date:{years['from']}-01-01,"
                f"to_publication_date:{years['until']}-12-31"
            )
    if api_key:
        params["api_key"] = api_key
    return "https://api.openalex.org/works?" + parse.urlencode(params)


def fetch_json(url: str, user_agent: str, timeout: float) -> tuple[dict[str, Any], dict[str, str]]:
    req = request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read(25 * 1024 * 1024 + 1)
        if len(raw) > 25 * 1024 * 1024:
            die("API response exceeded the 25 MiB safety limit")
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
        if not isinstance(payload, dict):
            die("API returned a non-object JSON payload")
        headers = {
            key: response.headers[key]
            for key in (
                "X-RateLimit-Limit",
                "X-RateLimit-Remaining",
                "X-RateLimit-Credits-Used",
                "X-RateLimit-Reset",
            )
            if response.headers.get(key) is not None
        }
        return payload, headers


def safe_network_error(exc: BaseException) -> str:
    if isinstance(exc, error.HTTPError):
        return f"HTTPError {exc.code}"
    if isinstance(exc, error.URLError):
        return f"URLError {type(exc.reason).__name__}"
    return type(exc).__name__


def parse_sources(value: str) -> list[str]:
    sources = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not sources or set(sources) - {"crossref", "openalex"}:
        die("--sources must be crossref, openalex, or crossref,openalex")
    return list(dict.fromkeys(sources))


def command_retrieve(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan)
    plan_data = load_json(plan_path)
    if plan_data.get("schema") != PLAN_SCHEMA:
        die(f"plan schema must be {PLAN_SCHEMA}")
    verify_payload_hash(plan_data, "search_plan_payload_sha256")
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        die(f"refusing to use existing retrieval directory: {output_dir}")
    (output_dir / "raw").mkdir(parents=True)
    sources = parse_sources(args.sources)
    all_queries = plan_data["queries"]
    if args.query_ids:
        requested_ids = [
            value.strip() for value in args.query_ids.split(",") if value.strip()
        ]
        if not requested_ids or len(requested_ids) != len(set(requested_ids)):
            die("--query-ids must contain unique comma-separated query IDs")
        query_by_id = {item["query_id"]: item for item in all_queries}
        unknown_ids = [query_id for query_id in requested_ids if query_id not in query_by_id]
        if unknown_ids:
            die(f"unknown --query-ids values: {', '.join(unknown_ids)}")
        queries = [query_by_id[query_id] for query_id in requested_ids]
    else:
        queries = all_queries[: args.max_queries or None]
    fixture_dir = Path(args.offline_fixture_dir) if args.offline_fixture_dir else None
    mailto = args.mailto or os.environ.get("CROSSREF_MAILTO")
    api_key = os.environ.get(args.openalex_api_key_env) if args.openalex_api_key_env else None
    entries: list[dict[str, Any]] = []
    successes = 0

    for query_spec in queries:
        for source in sources:
            entry: dict[str, Any] = {
                "query_id": query_spec["query_id"],
                "source": source,
                "mode": query_spec["mode"],
                "status": "pending",
            }
            fixture = fixture_dir / f"{query_spec['query_id']}.{source}.json" if fixture_dir else None
            if fixture_dir:
                if not fixture or not fixture.is_file():
                    entry["status"] = "fixture_missing"
                    entries.append(entry)
                    continue
                payload = load_json(fixture)
                request_url = f"offline-fixture://{fixture.name}"
                response_headers: dict[str, str] = {}
                entry["status"] = "fixture_replay"
            else:
                if source == "crossref" and not mailto:
                    entry["status"] = "skipped_missing_crossref_contact"
                    entries.append(entry)
                    continue
                if source == "crossref":
                    url = crossref_url(
                        query_spec, args.rows, plan_data.get("publication_years"), mailto
                    )
                    user_agent = (
                        "Auto-G16-Mechanism-TS-Literature/0.1 "
                        f"(mailto:{mailto})"
                    )
                else:
                    url = openalex_url(
                        query_spec, args.rows, plan_data.get("publication_years"), api_key
                    )
                    user_agent = "Auto-G16-Mechanism-TS-Literature/0.1"
                request_url = sanitized_url(url)
                try:
                    payload, response_headers = fetch_json(url, user_agent, args.timeout)
                    entry["status"] = "success"
                except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    entry["status"] = "failed"
                    entry["error"] = safe_network_error(exc)
                    entry["request_url"] = request_url
                    entries.append(entry)
                    if args.delay_seconds:
                        time.sleep(args.delay_seconds)
                    continue

            raw_path = output_dir / "raw" / f"{query_spec['query_id']}.{source}.json"
            write_json(raw_path, payload)
            entry.update(
                {
                    "request_url": request_url,
                    "raw_path": str(raw_path.relative_to(output_dir)),
                    "raw_sha256": sha256_path(raw_path),
                    "response_headers": response_headers,
                }
            )
            entries.append(entry)
            successes += 1
            if not fixture_dir and args.delay_seconds:
                time.sleep(args.delay_seconds)

    retrieval = {
        "schema": RETRIEVAL_SCHEMA,
        "request_id": plan_data["request_id"],
        "retrieved_at": utc_now(),
        "mode": "offline_fixture_replay" if fixture_dir else "live_metadata_api",
        "plan_artifact": {"path": str(plan_path), "sha256": sha256_path(plan_path)},
        "sources_requested": sources,
        "crossref_contact_supplied": bool(mailto),
        "openalex_api_key_supplied": bool(api_key),
        "rows_per_query": args.rows,
        "entries": entries,
        "summary": {
            "query_count": len(queries),
            "request_count": len(entries),
            "successful_payloads": successes,
            "failed_or_skipped_payloads": len(entries) - successes,
        },
        "limitations": [
            "Only metadata API payloads were retrieved; no publisher full text or SI was fetched.",
            "API relevance order and citation counts are discovery signals, not scientific evidence.",
        ],
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    retrieval = add_payload_hash(retrieval, "retrieval_payload_sha256")
    write_json(output_dir / "retrieval.json", retrieval)
    print(
        json.dumps(
            {"output_dir": str(output_dir), "successful_payloads": successes},
            ensure_ascii=False,
        )
    )


def clean_markup(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(text).split())


def first_text(value: Any) -> str | None:
    if isinstance(value, list) and value and isinstance(value[0], str):
        return clean_markup(value[0])
    return clean_markup(value)


def crossref_year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parts = item.get(key)
        if isinstance(parts, dict):
            date_parts = parts.get("date-parts")
            if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
                year = date_parts[0][0]
                if isinstance(year, int):
                    return year
    return None


def abstract_from_inverted(index: Any) -> str | None:
    if not isinstance(index, dict) or not index:
        return None
    positions: list[tuple[int, str]] = []
    for word, offsets in index.items():
        if isinstance(word, str) and isinstance(offsets, list):
            positions.extend((offset, word) for offset in offsets if isinstance(offset, int))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def normalize_crossref(payload: dict[str, Any], observation: dict[str, str]) -> list[dict[str, Any]]:
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("items"), list):
        items = message["items"]
    elif isinstance(message, dict):
        items = [message]
    else:
        return []
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        authors = []
        for author in item.get("author", []):
            if isinstance(author, dict):
                name = " ".join(
                    part for part in (author.get("given"), author.get("family")) if isinstance(part, str)
                )
                if name:
                    authors.append(name)
        records.append(
            {
                "doi": normalize_doi(item.get("DOI")),
                "title": first_text(item.get("title")),
                "authors": authors,
                "year": crossref_year(item),
                "venue": first_text(item.get("container-title")),
                "url": item.get("URL") if isinstance(item.get("URL"), str) else None,
                "publication_type": item.get("type"),
                "cited_by_count": item.get("is-referenced-by-count"),
                "record_status_signals": {
                    "crossref_update_to_present": bool(item.get("update-to")),
                    "crossref_relation_present": bool(item.get("relation")),
                    "openalex_is_retracted": None,
                },
                "abstract": clean_markup(item.get("abstract")),
                "observations": [observation],
            }
        )
    return records


def normalize_openalex(payload: dict[str, Any], observation: dict[str, str]) -> list[dict[str, Any]]:
    items = payload.get("results")
    if not isinstance(items, list):
        return []
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        authors = []
        for authorship in item.get("authorships", []):
            if isinstance(authorship, dict) and isinstance(authorship.get("author"), dict):
                name = authorship["author"].get("display_name")
                if isinstance(name, str):
                    authors.append(name)
        primary = item.get("primary_location")
        source = primary.get("source") if isinstance(primary, dict) else None
        venue = source.get("display_name") if isinstance(source, dict) else None
        doi = normalize_doi(item.get("doi"))
        records.append(
            {
                "doi": doi,
                "title": clean_markup(item.get("display_name") or item.get("title")),
                "authors": authors,
                "year": item.get("publication_year") if isinstance(item.get("publication_year"), int) else None,
                "venue": venue if isinstance(venue, str) else None,
                "url": f"https://doi.org/{doi}" if doi else item.get("id"),
                "publication_type": item.get("type"),
                "cited_by_count": item.get("cited_by_count"),
                "record_status_signals": {
                    "crossref_update_to_present": None,
                    "crossref_relation_present": None,
                    "openalex_is_retracted": (
                        item.get("is_retracted")
                        if isinstance(item.get("is_retracted"), bool)
                        else None
                    ),
                },
                "abstract": abstract_from_inverted(item.get("abstract_inverted_index")),
                "observations": [observation],
            }
        )
    return records


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    for symbol, name in (
        ("α", "alpha"),
        ("β", "beta"),
        ("γ", "gamma"),
        ("δ", "delta"),
        ("Α", "alpha"),
        ("Β", "beta"),
        ("Γ", "gamma"),
        ("Δ", "delta"),
    ):
        normalized = normalized.replace(symbol, name)
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    return " ".join(normalized.casefold().split())


def title_key(title: str) -> str:
    return re.sub(r"[\W_]+", "", normalize_search_text(title), flags=re.UNICODE)


def merge_records(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key in ("doi", "title", "authors", "year", "venue", "url", "publication_type", "abstract"):
        if not existing.get(key) and incoming.get(key):
            existing[key] = incoming[key]
    existing_signals = existing.setdefault("record_status_signals", {})
    for key, value in incoming.get("record_status_signals", {}).items():
        if value is True or key not in existing_signals:
            existing_signals[key] = value
    counts = [value for value in (existing.get("cited_by_count"), incoming.get("cited_by_count")) if isinstance(value, int)]
    existing["cited_by_count"] = max(counts) if counts else None
    existing["observations"].extend(incoming["observations"])


def term_hits(text: str, terms: list[str]) -> list[str]:
    folded = normalize_search_text(text)
    return [term for term in terms if normalize_search_text(term) in folded]


def score_record(record: dict[str, Any], ranking_terms: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    title = record.get("title") or ""
    abstract = record.get("abstract") or ""
    full = f"{title} {abstract}"
    hits = {
        "exact_phrases": term_hits(full, ranking_terms.get("exact_phrases", [])),
        "catalyst_terms": term_hits(full, ranking_terms.get("catalyst_terms", [])),
        "substrate_terms": term_hits(full, ranking_terms.get("substrate_terms", [])),
        "transformation_terms": term_hits(full, ranking_terms.get("transformation_terms", [])),
        "mechanism_terms": term_hits(full, ranking_terms.get("mechanism_terms", [])),
        "exclusions": term_hits(full, ranking_terms.get("exclusions", [])),
        "evidence_title": term_hits(title, list(EVIDENCE_WORDS)),
        "evidence_abstract": term_hits(abstract, list(EVIDENCE_WORDS)),
    }
    points = {
        "exact_phrases": min(10, 5 * len(hits["exact_phrases"])),
        "catalyst_terms": min(6, 3 * len(hits["catalyst_terms"])),
        "substrate_terms": min(6, 2 * len(hits["substrate_terms"])),
        "transformation_terms": min(6, 3 * len(hits["transformation_terms"])),
        "mechanism_terms": min(6, 2 * len(hits["mechanism_terms"])),
        "exclusions": -min(12, 6 * len(hits["exclusions"])),
        "evidence_title": min(9, 3 * len(hits["evidence_title"])),
        "evidence_abstract": min(6, len(hits["evidence_abstract"])),
    }
    return max(0, sum(points.values())), {"matched_terms": hits, "points": points}


def screening_tier(score: int, breakdown: dict[str, Any]) -> str:
    evidence_hits = breakdown["matched_terms"]["evidence_title"] + breakdown["matched_terms"]["evidence_abstract"]
    if score >= 12 and evidence_hits:
        return "high_priority_screen"
    if score >= 8:
        return "system_relevant_requires_full_text"
    if score >= 4:
        return "analogy_or_background_screen"
    return "low_lexical_match"


def command_rank(args: argparse.Namespace) -> None:
    plan_path, retrieval_path = Path(args.plan), Path(args.retrieval)
    plan_data, retrieval = load_json(plan_path), load_json(retrieval_path)
    if plan_data.get("schema") != PLAN_SCHEMA or retrieval.get("schema") != RETRIEVAL_SCHEMA:
        die("unexpected plan or retrieval schema")
    verify_payload_hash(plan_data, "search_plan_payload_sha256")
    verify_payload_hash(retrieval, "retrieval_payload_sha256")
    if retrieval.get("plan_artifact", {}).get("sha256") != sha256_path(plan_path):
        die("retrieval is not bound to the supplied search plan")
    query_lookup = {item["query_id"]: item for item in plan_data["queries"]}
    merged: dict[str, dict[str, Any]] = {}
    raw_record_count = 0
    for entry in retrieval["entries"]:
        if entry.get("status") not in {"success", "fixture_replay"}:
            continue
        raw_path = retrieval_path.parent / entry["raw_path"]
        if not raw_path.is_file() or sha256_path(raw_path) != entry["raw_sha256"]:
            die(f"raw payload missing or hash mismatch: {raw_path}")
        payload = load_json(raw_path)
        query = query_lookup.get(entry["query_id"], {})
        observation = {
            "source": entry["source"],
            "query_id": entry["query_id"],
            "lane": query.get("lane"),
            "raw_sha256": entry["raw_sha256"],
        }
        records = (
            normalize_crossref(payload, observation)
            if entry["source"] == "crossref"
            else normalize_openalex(payload, observation)
        )
        raw_record_count += len(records)
        for record in records:
            title = record.get("title")
            if not title:
                continue
            key = f"doi:{record['doi']}" if record.get("doi") else f"title:{title_key(title)}:{record.get('year') or 'unknown'}"
            if key in merged:
                merge_records(merged[key], record)
            else:
                merged[key] = record

    candidates = []
    for key, record in merged.items():
        score, breakdown = score_record(record, plan_data["ranking_terms"])
        observations = record.pop("observations")
        abstract = record.pop("abstract", None)
        candidate = {
            "candidate_id": "",
            "deduplication_key": key,
            **record,
            "metadata_abstract_available": bool(abstract),
            "discovery_observations": observations,
            "lexical_score": score,
            "score_breakdown": breakdown,
            "screening_tier": screening_tier(score, breakdown),
            "screening_status": "metadata_only_unverified",
            "directness": "not_reviewed",
        }
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            -item["lexical_score"],
            -(item.get("year") or 0),
            (item.get("title") or "").casefold(),
        )
    )
    if args.limit:
        candidates = candidates[: args.limit]
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = f"lit-{index:04d}"

    ledger = {
        "schema": LEDGER_SCHEMA,
        "request_id": plan_data["request_id"],
        "created_at": utc_now(),
        "search_plan_artifact": {"path": str(plan_path), "sha256": sha256_path(plan_path)},
        "retrieval_artifact": {"path": str(retrieval_path), "sha256": sha256_path(retrieval_path)},
        "target_evidence": plan_data["target_evidence"],
        "upstream_artifacts": plan_data.get("upstream_artifacts", {}),
        "w2_binding_status": plan_data.get("w2_binding_status"),
        "promotion_blockers": plan_data.get("promotion_blockers", []),
        "counts": {
            "normalized_raw_records": raw_record_count,
            "unique_candidates": len(merged),
            "candidates_retained": len(candidates),
        },
        "ranking_policy": {
            "type": "transparent_lexical_screening_only",
            "citation_count_used_in_score": False,
            "scientific_acceptance_performed": False,
        },
        "candidates": candidates,
        "limitations": [
            "No title, abstract, snippet, API relevance score, or citation count is accepted as mechanism or TS evidence.",
            "Primary article and version-matched SI review are still required.",
            "Preprint/version-of-record relations and corrections require manual verification.",
        ],
        "calculation_ready": False,
        "promotable_to_mechanism_support": False,
        "promotable_to_ts_precedent_map": False,
        "no_submission_authorization": True,
    }
    ledger = add_payload_hash(ledger, "candidate_ledger_payload_sha256")
    write_json(Path(args.output), ledger)
    if args.report:
        rows = [
            "# Auto-G16 Reaction Literature Screening Report",
            "",
            f"- Request: `{ledger['request_id']}`",
            f"- Raw normalized records: {raw_record_count}",
            f"- Unique records before output limit: {len(merged)}",
            f"- Retained candidates: {len(candidates)}",
            "- Status: metadata screening only; no mechanism or TS claim accepted",
            "",
            "| Rank | Score | Tier | Year | Title | DOI |",
            "|---:|---:|---|---:|---|---|",
        ]
        for index, item in enumerate(candidates[:30], start=1):
            title = (item.get("title") or "").replace("|", "\\|")
            doi = item.get("doi") or "—"
            rows.append(
                f"| {index} | {item['lexical_score']} | {item['screening_tier']} | "
                f"{item.get('year') or '—'} | {title} | {doi} |"
            )
        rows.extend(
            [
                "",
                "## Required next review",
                "",
                "Open the primary article and version-matched supporting information, record exact source locations, distinguish direct precedent from analogy, and leave unreported method/TS/IRC fields unresolved.",
                "",
            ]
        )
        write_text(Path(args.report), "\n".join(rows))
    print(json.dumps({"output": args.output, "candidates": len(candidates)}, ensure_ascii=False))


def command_init_review(args: argparse.Namespace) -> None:
    ledger_path = Path(args.ledger)
    ledger = load_json(ledger_path)
    if ledger.get("schema") != LEDGER_SCHEMA:
        die(f"ledger schema must be {LEDGER_SCHEMA}")
    verify_payload_hash(ledger, "candidate_ledger_payload_sha256")
    targets = ledger["target_evidence"]
    reviews = []
    for candidate in ledger["candidates"][: args.limit]:
        evidence = {
            target: {
                "status": "not_reviewed",
                "source_locations": [],
                "paraphrase": None,
            }
            for target in targets
        }
        reviews.append(
            {
                "candidate_id": candidate["candidate_id"],
                "bibliography": {
                    key: candidate.get(key)
                    for key in ("doi", "title", "authors", "year", "venue", "url", "publication_type")
                },
                "discovery": {
                    "lexical_score": candidate["lexical_score"],
                    "screening_tier": candidate["screening_tier"],
                    "metadata_only": True,
                },
                "source_checks": {
                    "doi_or_publisher_record_checked": False,
                    "primary_article_checked": False,
                    "supporting_information_checked": False,
                    "correction_or_retraction_checked": False,
                    "access_notes": [],
                },
                "directness_dimensions": {
                    "net_transformation": "unknown",
                    "elementary_step_and_atom_correspondence": "unknown",
                    "substrate_electronics_sterics_and_groups": "unknown",
                    "catalyst_and_active_state": "unknown",
                    "atom_inventory_charge_multiplicity_and_spin": "unknown",
                    "coordination_ion_pair_additives_and_solvent": "unknown",
                    "stereochemical_channel": "unknown",
                    "experimental_conditions": "unknown",
                    "computational_protocol_and_validation": "unknown",
                },
                "evidence": evidence,
                "reported_protocol": {
                    "status": "not_reviewed_not_approved_protocol",
                    "optimization_frequency": None,
                    "single_point": None,
                    "solvation": None,
                    "dispersion": None,
                    "temperature_k": None,
                    "standard_state": None,
                    "low_frequency_treatment": None,
                    "program_version": None,
                },
                "reported_ts_path": {
                    "ts_labels": [],
                    "charge_multiplicity": None,
                    "model_truncations": None,
                    "imaginary_frequencies_cm1": [],
                    "normal_mode_interpretation": None,
                    "irc_directions_reported": [],
                    "identified_endpoints": [],
                    "coordinates_available": None,
                },
                "exact_quotes": [],
                "reviewer_decision": {
                    "status": "pending",
                    "bounded_use": None,
                    "rationale": None,
                    "reviewed_at": None,
                },
            }
        )
    review = {
        "schema": REVIEW_SCHEMA,
        "request_id": ledger["request_id"],
        "created_at": utc_now(),
        "record_status": "editable_review_template",
        "candidate_ledger_artifact": {"path": str(ledger_path), "sha256": sha256_path(ledger_path)},
        "upstream_artifacts": ledger.get("upstream_artifacts", {}),
        "w2_binding_status": ledger.get("w2_binding_status"),
        "promotion_blockers": ledger.get("promotion_blockers", []),
        "allowed_evidence_statuses": ["not_reviewed", "not_found", "source_ambiguous", "source_reports"],
        "allowed_decisions": [
            "pending",
            "source_checked_background",
            "source_reports_analogy",
            "source_reports_direct_precedent",
            "exclude",
        ],
        "allowed_applicability_values": [
            "exact",
            "close",
            "remote",
            "contradictory",
            "unknown",
            "not_applicable",
        ],
        "allowed_bounded_uses": [
            "discovery_only",
            "mechanism_support",
            "ts_topology_support",
            "geometry_seed_support",
            "protocol_candidate_support",
            "not_applicable_to_target",
        ],
        "reviews": reviews,
        "calculation_ready": False,
        "promotable_to_mechanism_support": False,
        "promotable_to_ts_precedent_map": False,
        "no_submission_authorization": True,
        "evidence_review_payload_sha256": None,
    }
    write_json(Path(args.output), review)
    print(json.dumps({"output": args.output, "reviews": len(reviews)}, ensure_ascii=False))


def resolve_artifact(reference: str, base: Path) -> Path | None:
    direct = Path(reference)
    if direct.is_file():
        return direct
    relative = base / reference
    return relative if relative.is_file() else None


def command_validate_review(args: argparse.Namespace) -> None:
    review_path = Path(args.review)
    review = load_json(review_path)
    if review.get("schema") != REVIEW_SCHEMA:
        die(f"review schema must be {REVIEW_SCHEMA}")
    if review.get("evidence_review_payload_sha256"):
        verify_payload_hash(review, "evidence_review_payload_sha256")
    if (
        review.get("calculation_ready") is not False
        or review.get("no_submission_authorization") is not True
        or review.get("promotable_to_mechanism_support") is not False
        or review.get("promotable_to_ts_precedent_map") is not False
    ):
        die("literature review must remain calculation_ready false and non-authorizing")
    ledger_ref = review.get("candidate_ledger_artifact", {})
    if not isinstance(ledger_ref, dict) or not isinstance(ledger_ref.get("path"), str):
        die("candidate_ledger_artifact binding is required")
    ledger_path = resolve_artifact(ledger_ref["path"], review_path.parent)
    if ledger_path is None:
        die("candidate ledger artifact cannot be resolved for hash validation")
    if sha256_path(ledger_path) != ledger_ref.get("sha256"):
        die("candidate ledger hash mismatch")
    ledger = load_json(ledger_path)
    if ledger.get("schema") != LEDGER_SCHEMA:
        die("candidate ledger schema mismatch")
    verify_payload_hash(ledger, "candidate_ledger_payload_sha256")
    if ledger.get("request_id") != review.get("request_id"):
        die("candidate ledger and evidence review request IDs differ")
    ledger_candidate_ids = {
        item.get("candidate_id")
        for item in ledger.get("candidates", [])
        if isinstance(item, dict)
    }
    ledger_candidates = {
        item["candidate_id"]: item
        for item in ledger.get("candidates", [])
        if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
    }

    allowed_evidence = {"not_reviewed", "not_found", "source_ambiguous", "source_reports"}
    allowed_decisions = {
        "pending",
        "source_checked_background",
        "source_reports_analogy",
        "source_reports_direct_precedent",
        "exclude",
    }
    allowed_applicability = {
        "exact",
        "close",
        "remote",
        "contradictory",
        "unknown",
        "not_applicable",
    }
    allowed_bounded_uses = {
        "discovery_only",
        "mechanism_support",
        "ts_topology_support",
        "geometry_seed_support",
        "protocol_candidate_support",
        "not_applicable_to_target",
    }
    source_types = {
        "primary_article",
        "supporting_information",
        "correction_or_retraction_notice",
        "repository_author_manuscript",
        "dissertation_or_thesis",
    }
    expected_dimensions = {
        "net_transformation",
        "elementary_step_and_atom_correspondence",
        "substrate_electronics_sterics_and_groups",
        "catalyst_and_active_state",
        "atom_inventory_charge_multiplicity_and_spin",
        "coordination_ion_pair_additives_and_solvent",
        "stereochemical_channel",
        "experimental_conditions",
        "computational_protocol_and_validation",
    }
    expected_evidence = set(ledger.get("target_evidence", []))
    accepted = 0
    reviews = review.get("reviews")
    if not isinstance(reviews, list):
        die("reviews must be a list")
    seen_candidate_ids: set[str] = set()
    for review_index, item in enumerate(reviews):
        if not isinstance(item, dict):
            die(f"reviews[{review_index}] must be an object")
        candidate_id = item.get("candidate_id", "unknown")
        if candidate_id not in ledger_candidate_ids:
            die(f"{candidate_id}: review candidate is absent from the bound ledger")
        if candidate_id in seen_candidate_ids:
            die(f"{candidate_id}: duplicate review candidate")
        seen_candidate_ids.add(candidate_id)
        candidate = ledger_candidates[candidate_id]
        bibliography = item.get("bibliography")
        if not isinstance(bibliography, dict):
            die(f"{candidate_id}: bibliography must be an object")
        if normalize_doi(bibliography.get("doi")) != normalize_doi(candidate.get("doi")):
            die(f"{candidate_id}: bibliography DOI differs from the bound candidate ledger")
        bibliography_title = bibliography.get("title")
        candidate_title = candidate.get("title")
        if (
            not isinstance(bibliography_title, str)
            or not isinstance(candidate_title, str)
            or normalize_search_text(bibliography_title)
            != normalize_search_text(candidate_title)
        ):
            die(f"{candidate_id}: bibliography title differs from the bound candidate ledger")
        source_checks = item.get("source_checks", {})
        if not isinstance(source_checks, dict):
            die(f"{candidate_id}: source_checks must be an object")
        for field in (
            "doi_or_publisher_record_checked",
            "primary_article_checked",
            "supporting_information_checked",
            "correction_or_retraction_checked",
        ):
            if type(source_checks.get(field)) is not bool:
                die(f"{candidate_id}: source_checks.{field} must be boolean")
        access_notes = source_checks.get("access_notes")
        if not isinstance(access_notes, list) or any(
            not isinstance(note, str) or not note.strip() for note in access_notes
        ):
            die(f"{candidate_id}: source_checks.access_notes must be a list of non-empty strings")
        evidence = item.get("evidence", {})
        if not isinstance(evidence, dict):
            die(f"{candidate_id}: evidence must be an object")
        if set(evidence) != expected_evidence:
            die(f"{candidate_id}: evidence fields must exactly match the bound target_evidence")
        for target, claim in evidence.items():
            if not isinstance(claim, dict) or claim.get("status") not in allowed_evidence:
                die(f"{candidate_id}/{target}: invalid evidence status")
            if claim["status"] == "source_reports":
                locations = claim.get("source_locations")
                if not isinstance(locations, list) or not locations:
                    die(f"{candidate_id}/{target}: source_reports requires a source location")
                if not isinstance(claim.get("paraphrase"), str) or not claim["paraphrase"].strip():
                    die(f"{candidate_id}/{target}: source_reports requires a paraphrase")
                for location in locations:
                    if not isinstance(location, dict) or any(
                        not isinstance(location.get(field), str) or not location[field].strip()
                        for field in ("source_type", "locator", "url_or_doi", "checked_at")
                    ):
                        die(f"{candidate_id}/{target}: incomplete source location")
                    if location["source_type"] not in source_types:
                        die(f"{candidate_id}/{target}: source type is not primary evidence")
        protocol = item.get("reported_protocol")
        if not isinstance(protocol, dict) or protocol.get("status") not in {
            "not_reviewed_not_approved_protocol",
            "source_reported_not_approved_protocol",
            "source_ambiguous_not_approved_protocol",
            "source_incomplete_not_approved_protocol",
        }:
            die(f"{candidate_id}: invalid reported protocol status")
        protocol_has_values = any(
            value is not None
            for field, value in protocol.items()
            if field != "status"
        )
        protocol_claim = evidence.get("computational_protocol", {})
        if (
            protocol_has_values
            or protocol["status"] != "not_reviewed_not_approved_protocol"
        ) and protocol_claim.get("status") != "source_reports":
            die(
                f"{candidate_id}: reported protocol details require source-located computational_protocol evidence"
            )
        ts_path = item.get("reported_ts_path")
        if not isinstance(ts_path, dict):
            die(f"{candidate_id}: reported_ts_path must be an object")
        ts_path_has_values = any(
            value not in (None, [], {}) for value in ts_path.values()
        )
        ts_claim_statuses = {
            evidence.get(target, {}).get("status")
            for target in ("transition_state_model", "normal_mode", "irc", "coordinates")
            if target in evidence
        }
        if ts_path_has_values and "source_reports" not in ts_claim_statuses:
            die(
                f"{candidate_id}: reported TS/path details require source-located TS, mode, IRC, or coordinate evidence"
            )
        dimensions = item.get("directness_dimensions")
        if not isinstance(dimensions, dict) or set(dimensions) != expected_dimensions:
            die(f"{candidate_id}: all nine directness_dimensions are required")
        if any(value not in allowed_applicability for value in dimensions.values()):
            die(f"{candidate_id}: invalid applicability dimension value")
        quotes = item.get("exact_quotes")
        if not isinstance(quotes, list):
            die(f"{candidate_id}: exact_quotes must be a list")
        for quote in quotes:
            if not isinstance(quote, dict) or not isinstance(quote.get("text"), str):
                die(f"{candidate_id}: malformed exact quote")
            if len(quote["text"].split()) > 25:
                die(f"{candidate_id}: exact quote exceeds 25 words")
            if not quote.get("locator"):
                die(f"{candidate_id}: exact quote requires a locator")
        decision = item.get("reviewer_decision", {})
        status = decision.get("status")
        if status not in allowed_decisions:
            die(f"{candidate_id}: invalid reviewer decision")
        if status != "pending":
            if not isinstance(decision.get("rationale"), str) or not decision["rationale"].strip():
                die(f"{candidate_id}: non-pending decision requires a rationale")
            if source_checks.get("doi_or_publisher_record_checked") is not True:
                die(f"{candidate_id}: decision requires DOI/publisher verification")
            if decision.get("bounded_use") not in allowed_bounded_uses:
                die(f"{candidate_id}: non-pending decision requires a bounded use")
            if not isinstance(decision.get("reviewed_at"), str) or not decision["reviewed_at"].strip():
                die(f"{candidate_id}: non-pending decision requires reviewed_at")
            if status in {"source_reports_analogy", "source_reports_direct_precedent"} and source_checks.get("primary_article_checked") is not True:
                die(f"{candidate_id}: precedent decision requires primary-article review")
            if status in {"source_reports_analogy", "source_reports_direct_precedent"} and not any(
                claim.get("status") == "source_reports" for claim in evidence.values()
            ):
                die(f"{candidate_id}: precedent decision requires source-located evidence")
            if status == "source_reports_direct_precedent" and any(
                value not in {"exact", "not_applicable"}
                for value in dimensions.values()
            ):
                die(
                    f"{candidate_id}: direct precedent requires every applicability dimension to be exact or not_applicable"
                )
            accepted += 1
    result = {
        "valid": True,
        "reviews": len(review.get("reviews", [])),
        "non_pending_decisions": accepted,
    }
    if args.output:
        finalized = dict(review)
        finalized["record_status"] = "validated_review_record"
        finalized["validated_at"] = utc_now()
        finalized = add_payload_hash(finalized, "evidence_review_payload_sha256")
        write_json(Path(args.output), finalized)
        result["output"] = args.output
        result["evidence_review_payload_sha256"] = finalized[
            "evidence_review_payload_sha256"
        ]
    else:
        unhashed = dict(review)
        unhashed.pop("evidence_review_payload_sha256", None)
        result["current_content_sha256"] = hashlib.sha256(
            canonical_bytes(unhashed)
        ).hexdigest()
        result["note"] = "validated but not finalized; use --output for a hash-bound record"
    print(json.dumps(result, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan, retrieve, screen, and audit reaction mechanism/TS literature."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Build a hash-bound search plan offline")
    plan.add_argument("intake")
    plan.add_argument("--output", required=True)
    plan.set_defaults(func=command_plan)

    retrieve = subparsers.add_parser("retrieve", help="Retrieve metadata or replay offline fixtures")
    retrieve.add_argument("plan")
    retrieve.add_argument("--output-dir", required=True)
    retrieve.add_argument("--sources", default="crossref,openalex")
    retrieve.add_argument("--rows", type=int, default=20, choices=range(1, 101), metavar="1..100")
    retrieve.add_argument("--max-queries", type=int)
    retrieve.add_argument(
        "--query-ids",
        help="Retrieve only these comma-separated plan query IDs, in the given order",
    )
    retrieve.add_argument("--mailto")
    retrieve.add_argument("--openalex-api-key-env", default="OPENALEX_API_KEY")
    retrieve.add_argument("--offline-fixture-dir")
    retrieve.add_argument("--timeout", type=float, default=30.0)
    retrieve.add_argument("--delay-seconds", type=float, default=0.2)
    retrieve.set_defaults(func=command_retrieve)

    rank = subparsers.add_parser("rank", help="Normalize, deduplicate, and lexically screen metadata")
    rank.add_argument("plan")
    rank.add_argument("retrieval")
    rank.add_argument("--output", required=True)
    rank.add_argument("--report")
    rank.add_argument("--limit", type=int)
    rank.set_defaults(func=command_rank)

    review = subparsers.add_parser("init-review", help="Create a source-review ledger")
    review.add_argument("ledger")
    review.add_argument("--output", required=True)
    review.add_argument("--limit", type=int, default=20)
    review.set_defaults(func=command_init_review)

    validate = subparsers.add_parser("validate-review", help="Validate a completed source-review ledger")
    validate.add_argument("review")
    validate.add_argument("--output", help="Write a new finalized, hash-bound review record")
    validate.set_defaults(func=command_validate_review)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "max_queries", None) is not None and args.max_queries < 1:
        die("--max-queries must be positive")
    if getattr(args, "max_queries", None) is not None and getattr(args, "query_ids", None):
        die("use either --max-queries or --query-ids, not both")
    if getattr(args, "limit", None) is not None and args.limit < 1:
        die("--limit must be positive")
    args.func(args)


if __name__ == "__main__":
    main()
