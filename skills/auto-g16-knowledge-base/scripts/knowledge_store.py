#!/usr/bin/env python3
"""Immutable store and deterministic SQLite index for Auto-G16 W2 records."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import knowledge_base as contracts


STORE_SCHEMA = "auto-g16-knowledge-store/1"
INDEX_SCHEMA = "auto-g16-knowledge-index/1"
PRINCIPAL_SCHEMA = "auto-g16-knowledge-principal/1"
STORE_FORMAT_VERSION = 1
INDEX_FORMAT_VERSION = 1
STORE_RECORD_TYPES = {"structure", "method", "source", "link", "snapshot"}
MIGRATION = Path(__file__).with_name("migrations") / "001_initial.sql"

INDEX_TABLE_ORDER = (
    "records",
    "aliases",
    "external_identifiers",
    "issues",
    "structure_keys",
    "method_facts",
    "source_anchors",
    "source_claims",
    "links",
    "objects",
    "record_object_refs",
    "snapshot_members",
)


class StoreError(ValueError):
    """The local W2 store or derived index violated its offline contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StoreError(message)


def json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_hash(value: dict[str, Any], field: str) -> str:
    payload = copy.deepcopy(value)
    payload.pop(field, None)
    return contracts.sha256_data(payload)


def finalize_document(value: dict[str, Any], field: str) -> dict[str, Any]:
    value[field] = document_hash(value, field)
    return value


def verify_document_hash(value: dict[str, Any], field: str, label: str) -> None:
    contracts.sha256(value.get(field), f"{label}.{field}")
    require(value[field] == document_hash(value, field), f"{label} hash mismatch")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_store_id(path: Path) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", path.name.casefold()).strip("_")
    if not value or not value[0].isalpha():
        value = f"store_{value or 'knowledge'}"
    if len(value) < 3:
        value = f"store_{value}"
    return value[:64]


def reject_symlink(path: Path, label: str) -> None:
    require(not path.is_symlink(), f"{label} must not be a symlink: {path}")


def require_directory(path: Path, label: str) -> Path:
    reject_symlink(path, label)
    require(path.is_dir(), f"{label} is not a directory: {path}")
    return path.resolve()


def ensure_tree_has_no_symlinks(root: Path) -> None:
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in directory_names:
            reject_symlink(current_path / name, "store directory")
        for name in file_names:
            reject_symlink(current_path / name, "store file")


def validate_store_manifest(value: dict[str, Any]) -> None:
    fields = {
        "schema",
        "store_id",
        "format_version",
        "created_at",
        "record_layout",
        "object_layout",
        "calculation_ready",
        "no_submission_authorization",
        "manifest_sha256",
    }
    contracts.exact_keys(value, fields, fields, "store manifest")
    require(value["schema"] == STORE_SCHEMA, f"store manifest schema must be {STORE_SCHEMA}")
    contracts.identifier(value["store_id"], "store manifest.store_id")
    require(value["format_version"] == STORE_FORMAT_VERSION, "unsupported store format version")
    contracts.timestamp(value["created_at"], "store manifest.created_at")
    require(
        value["record_layout"] == "records/{record_type}/{record_id}/{revision_id}.json",
        "unsupported record layout",
    )
    require(
        value["object_layout"] == "objects/sha256/{prefix}/{sha256}",
        "unsupported object layout",
    )
    require(value["calculation_ready"] is False, "store manifest cannot grant calculation readiness")
    require(value["no_submission_authorization"] is True, "store manifest cannot grant submission authority")
    verify_document_hash(value, "manifest_sha256", "store manifest")


def init_store(root_path: Path, store_id: str | None, created_at: str | None) -> dict[str, Any]:
    reject_symlink(root_path, "store root")
    if root_path.exists():
        require(root_path.is_dir(), f"store root exists and is not a directory: {root_path}")
        require(not any(root_path.iterdir()), f"refusing to initialize non-empty store: {root_path}")
    else:
        root_path.mkdir(parents=True)
    root = root_path.resolve()
    resolved_id = store_id or normalize_store_id(root)
    contracts.identifier(resolved_id, "store_id")
    timestamp = created_at or utc_now()
    contracts.timestamp(timestamp, "created_at")

    for record_type in sorted(STORE_RECORD_TYPES):
        (root / "records" / record_type).mkdir(parents=True)
    (root / "objects" / "sha256").mkdir(parents=True)
    (root / "indexes").mkdir(parents=True)

    manifest = finalize_document(
        {
            "schema": STORE_SCHEMA,
            "store_id": resolved_id,
            "format_version": STORE_FORMAT_VERSION,
            "created_at": timestamp,
            "record_layout": "records/{record_type}/{record_id}/{revision_id}.json",
            "object_layout": "objects/sha256/{prefix}/{sha256}",
            "calculation_ready": False,
            "no_submission_authorization": True,
        },
        "manifest_sha256",
    )
    contracts.write_json(root / "store.json", manifest)
    return manifest


def load_store_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "store.json"
    reject_symlink(manifest_path, "store manifest")
    require(manifest_path.is_file(), f"store manifest is missing: {manifest_path}")
    manifest = contracts.load_json(manifest_path)
    validate_store_manifest(manifest)
    return manifest


def record_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        contracts.SCHEMAS[record["schema"]],
        record["record_id"],
        record["revision_id"],
    )


def record_ref_key(ref: dict[str, Any]) -> tuple[str, str, str]:
    return (ref["record_type"], ref["record_id"], ref["revision_id"])


def scan_records(root: Path) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str, str], str]]:
    records_root = require_directory(root / "records", "records root")
    directory_names = {path.name for path in records_root.iterdir() if path.is_dir()}
    file_names = {path.name for path in records_root.iterdir() if path.is_file()}
    require(not file_names, f"unexpected files at records root: {', '.join(sorted(file_names))}")
    require(directory_names == STORE_RECORD_TYPES, "records root does not contain the exact record-type directories")

    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    paths: dict[tuple[str, str, str], str] = {}
    payload_hashes: set[str] = set()
    for path in sorted(records_root.rglob("*")):
        reject_symlink(path, "record path")
        if path.is_dir():
            continue
        relative = path.relative_to(root)
        require(len(relative.parts) == 4, f"record is outside the canonical layout: {relative}")
        _, record_type, path_record_id, filename = relative.parts
        require(record_type in STORE_RECORD_TYPES, f"unsupported record directory: {record_type}")
        require(path.suffix == ".json", f"record must use .json extension: {relative}")
        path_revision_id = path.stem
        contracts.identifier(path_record_id, f"record path ID in {relative}")
        contracts.identifier(path_revision_id, f"revision path ID in {relative}")
        record = contracts.load_json(path)
        contracts.validate_record(record)
        require(path.read_bytes() == contracts.canonical_bytes(record), f"record file is not canonical JSON: {relative}")
        key = record_key(record)
        require(key[0] == record_type, f"record type does not match path: {relative}")
        require(key[1] == path_record_id, f"record_id does not match path: {relative}")
        require(key[2] == path_revision_id, f"revision_id does not match path: {relative}")
        require(key not in records, f"duplicate record revision: {key}")
        require(record["payload_sha256"] not in payload_hashes, f"duplicate canonical payload hash: {record['payload_sha256']}")
        payload_hashes.add(record["payload_sha256"])
        records[key] = record
        paths[key] = relative.as_posix()
    return records, paths


def extract_object_refs(
    records: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for key, record in sorted(records.items()):
        if key[0] == "structure":
            for representation in record["representations"]:
                refs.append(
                    {
                        "record_key": key,
                        "role": f"representation:{representation['representation_id']}",
                        "object": representation["object"],
                    }
                )
        elif key[0] == "source":
            for index, obj in enumerate(record["objects"]):
                refs.append(
                    {
                        "record_key": key,
                        "role": f"source_object:{index:04d}",
                        "object": obj,
                    }
                )
    return refs


def scan_objects(root: Path, object_refs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    object_root = require_directory(root / "objects" / "sha256", "object root")
    referenced: dict[str, dict[str, Any]] = {}
    lawful_required: set[str] = set()
    for ref in object_refs:
        obj = ref["object"]
        digest = obj["sha256"]
        existing = referenced.get(digest)
        if existing is not None:
            require(existing["size_bytes"] == obj["size_bytes"], f"object size metadata conflicts for {digest}")
            require(existing["media_type"] == obj["media_type"], f"object media type conflicts for {digest}")
        else:
            referenced[digest] = {
                "sha256": digest,
                "size_bytes": obj["size_bytes"],
                "media_type": obj["media_type"],
                "present_local": False,
            }
        if obj["storage_status"] == "lawful_local_object":
            lawful_required.add(digest)

    present: set[str] = set()
    for path in sorted(object_root.rglob("*")):
        reject_symlink(path, "object path")
        if path.is_dir():
            continue
        relative = path.relative_to(root)
        require(len(relative.parts) == 4, f"object is outside content-addressed layout: {relative}")
        _, algorithm, prefix, filename = relative.parts
        require(algorithm == "sha256", f"unsupported object hash algorithm: {algorithm}")
        contracts.sha256(filename, f"object filename in {relative}")
        require(prefix == filename[:2], f"object prefix does not match hash: {relative}")
        actual = hash_file(path)
        require(actual == filename, f"object content hash mismatch: {relative}")
        require(filename in referenced, f"unreferenced object is not permitted in canonical store: {relative}")
        require(path.stat().st_size == referenced[filename]["size_bytes"], f"object size mismatch: {relative}")
        present.add(filename)
        referenced[filename]["present_local"] = True

    missing = sorted(lawful_required - present)
    require(not missing, f"lawfully retained objects are missing: {', '.join(missing)}")
    return referenced


def resolve_ref(
    ref: dict[str, Any],
    records: dict[tuple[str, str, str], dict[str, Any]],
    label: str,
) -> dict[str, Any] | None:
    key = record_ref_key(ref)
    if key[0] not in STORE_RECORD_TYPES:
        return None
    require(key in records, f"{label} references a missing record revision: {key}")
    target = records[key]
    require(target["payload_sha256"] == ref["payload_sha256"], f"{label} payload hash mismatch")
    return target


def validate_anchor_ref_against_store(
    anchor_ref: dict[str, Any],
    records: dict[tuple[str, str, str], dict[str, Any]],
    label: str,
) -> None:
    source = resolve_ref(anchor_ref["source_record"], records, f"{label}.source_record")
    require(source is not None and source["schema"] == "auto-g16-source-record/1", f"{label} does not resolve to a source record")
    anchor_ids = {item["anchor_id"] for item in source["anchors"]}
    require(anchor_ref["anchor_id"] in anchor_ids, f"{label} references an unknown source anchor")


def validate_snapshot_against_records(
    snapshot: dict[str, Any],
    records: dict[tuple[str, str, str], dict[str, Any]],
    label: str,
) -> None:
    for index, member in enumerate(snapshot["included_records"]):
        target = resolve_ref(member, records, f"{label}.included_records[{index}]")
        require(target is not None, f"{label}.included_records[{index}] must resolve locally")
        require(target["review"]["status"] == member["review_status"], f"{label}.included_records[{index}] review status drift")
        require(target["access"]["class"] == member["access_class"], f"{label}.included_records[{index}] access class drift")
    for index, decision in enumerate(snapshot["selection_decisions"]):
        require(
            resolve_ref(decision["record_ref"], records, f"{label}.selection_decisions[{index}]") is not None,
            f"{label}.selection_decisions[{index}] must resolve locally",
        )


def validate_cross_references(records: dict[tuple[str, str, str], dict[str, Any]]) -> None:
    for key, record in sorted(records.items()):
        label = f"record {key}"
        if key[0] == "structure":
            if record["record_scope"] == "state":
                parent = resolve_ref(record["parent_identity"], records, f"{label}.parent_identity")
                require(parent is not None and parent.get("record_scope") == "identity", f"{label}.parent_identity is not an identity record")
            elif record["record_scope"] == "geometry":
                parent = resolve_ref(record["parent_state"], records, f"{label}.parent_state")
                require(parent is not None and parent.get("record_scope") == "state", f"{label}.parent_state is not a state record")
            for rep_index, representation in enumerate(record["representations"]):
                for ref_index, ref in enumerate(representation["supporting_record_refs"]):
                    resolve_ref(ref, records, f"{label}.representations[{rep_index}].supporting_record_refs[{ref_index}]")
        elif key[0] == "method":
            for field_name, fact in record["protocol"].items():
                for index, anchor_ref in enumerate(fact["source_anchor_refs"]):
                    validate_anchor_ref_against_store(anchor_ref, records, f"{label}.protocol.{field_name}.source_anchor_refs[{index}]")
            for field in ("supporting_source_refs", "benchmark_record_refs", "failure_record_refs"):
                for index, ref in enumerate(record["evidence"][field]):
                    resolve_ref(ref, records, f"{label}.evidence.{field}[{index}]")
        elif key[0] == "link":
            resolve_ref(record["source"], records, f"{label}.source")
            resolve_ref(record["target"], records, f"{label}.target")
            for index, anchor_ref in enumerate(record["source_anchors"]):
                validate_anchor_ref_against_store(anchor_ref, records, f"{label}.source_anchors[{index}]")
            for index, ref in enumerate(record["evidence_record_refs"]):
                resolve_ref(ref, records, f"{label}.evidence_record_refs[{index}]")
        elif key[0] == "snapshot":
            validate_snapshot_against_records(record, records, label)


def store_content_digest(
    records: dict[tuple[str, str, str], dict[str, Any]],
    objects: dict[str, dict[str, Any]],
) -> str:
    content = {
        "records": [
            {
                "record_type": key[0],
                "record_id": key[1],
                "revision_id": key[2],
                "payload_sha256": record["payload_sha256"],
            }
            for key, record in sorted(records.items())
        ],
        "objects": [objects[digest] for digest in sorted(objects)],
    }
    return contracts.sha256_data(content)


def verify_store(root_path: Path) -> dict[str, Any]:
    root = require_directory(root_path, "store root")
    ensure_tree_has_no_symlinks(root)
    allowed_top = {"store.json", "records", "objects", "indexes"}
    top_names = {path.name for path in root.iterdir()}
    require(top_names == allowed_top, f"store root contains unexpected or missing entries: {sorted(top_names ^ allowed_top)}")
    manifest = load_store_manifest(root)
    records, record_paths = scan_records(root)
    object_refs = extract_object_refs(records)
    objects = scan_objects(root, object_refs)
    validate_cross_references(records)
    duplicate_report = contracts.audit_record_set(list(records.values()))
    return {
        "root": root,
        "manifest": manifest,
        "records": records,
        "record_paths": record_paths,
        "object_refs": object_refs,
        "objects": objects,
        "duplicate_candidates": duplicate_report["duplicate_candidates"],
        "conflicts": duplicate_report["conflicts"],
        "content_digest": store_content_digest(records, objects),
    }


def build_index_rows(inventory: dict[str, Any]) -> dict[str, list[tuple[Any, ...]]]:
    rows: dict[str, list[tuple[Any, ...]]] = {name: [] for name in INDEX_TABLE_ORDER}
    records = inventory["records"]
    object_refs_by_record: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for ref in inventory["object_refs"]:
        object_refs_by_record.setdefault(ref["record_key"], []).append(ref)

    for key, record in sorted(records.items()):
        rows["records"].append(
            (
                key[0], key[1], key[2], record["schema"], record["payload_sha256"],
                record["review"]["status"], record["access"]["class"],
                record["access"]["owner_project"], json_text(record["access"]["permitted_principals"]),
                record["access"]["export_policy"], record["created_at"], inventory["record_paths"][key],
            )
        )
        for alias in record["aliases"]:
            rows["aliases"].append((key[0], key[1], key[2], alias["type"], alias["value"]))
        for external in record["external_identifiers"]:
            rows["external_identifiers"].append((key[0], key[1], key[2], external["scheme"], external["value"]))
        for issue_class in ("uncertainties", "contradictions", "blockers"):
            for issue in record[issue_class]:
                rows["issues"].append((key[0], key[1], key[2], issue_class, issue["code"], issue["message"], json_text(issue["source_refs"])))
        if key[0] == "structure":
            identity = record["identity"] or {}
            parent = record["parent_identity"] or record["parent_state"]
            rows["structure_keys"].append((
                "structure", key[1], key[2], record["record_scope"], identity.get("formula"),
                identity.get("canonical_smiles"), identity.get("inchikey"),
                parent.get("record_id") if parent else None, parent.get("revision_id") if parent else None,
            ))
        elif key[0] == "method":
            for field_name, fact in sorted(record["protocol"].items()):
                rows["method_facts"].append(("method", key[1], key[2], field_name, fact["status"], json_text(fact["value"]), json_text(fact["source_anchor_refs"])))
        elif key[0] == "source":
            for anchor in record["anchors"]:
                rows["source_anchors"].append(("source", key[1], key[2], anchor["anchor_id"], anchor["locator_type"], anchor["locator"], anchor["object_sha256"]))
            for claim in record["claims"]:
                rows["source_claims"].append(("source", key[1], key[2], claim["claim_id"], claim["category"], claim["statement_type"], claim["review_status"], json_text(claim["anchor_ids"])))
        elif key[0] == "link":
            rows["links"].append((
                "link", key[1], key[2], record["relation_type"],
                record["source"]["record_type"], record["source"]["record_id"], record["source"]["revision_id"], record["source"]["payload_sha256"],
                record["target"]["record_type"], record["target"]["record_id"], record["target"]["revision_id"], record["target"]["payload_sha256"],
                record["evidence_directness"], record["scope"],
            ))
        elif key[0] == "snapshot":
            for member in record["included_records"]:
                rows["snapshot_members"].append((
                    "snapshot", key[1], key[2], member["record_type"], member["record_id"], member["revision_id"],
                    member["payload_sha256"], member["review_status"], member["access_class"],
                ))
        for ref in object_refs_by_record.get(key, []):
            obj = ref["object"]
            rows["record_object_refs"].append((key[0], key[1], key[2], obj["sha256"], ref["role"], obj["storage_status"]))

    for digest, obj in sorted(inventory["objects"].items()):
        rows["objects"].append((digest, obj["size_bytes"], obj["media_type"], int(obj["present_local"])))
    for name in rows:
        rows[name].sort(key=lambda item: contracts.canonical_bytes(list(item)))
    return rows


def row_digest(rows: dict[str, list[tuple[Any, ...]]]) -> str:
    return contracts.sha256_data(
        [{"table": table, "rows": [list(row) for row in rows[table]]} for table in INDEX_TABLE_ORDER]
    )


def index_manifest_path(index_path: Path) -> Path:
    return Path(str(index_path) + ".manifest.json")


def rebuild_index(store_path: Path, output_path: Path) -> dict[str, Any]:
    require(not output_path.exists(), f"refusing to overwrite existing index: {output_path}")
    manifest_path = index_manifest_path(output_path)
    require(not manifest_path.exists(), f"refusing to overwrite existing index manifest: {manifest_path}")
    require(MIGRATION.is_file(), f"SQLite migration is missing: {MIGRATION}")
    inventory = verify_store(store_path)
    rows = build_index_rows(inventory)
    canonical_digest = row_digest(rows)
    migration_sha256 = hash_file(MIGRATION)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary = tempfile.NamedTemporaryFile(prefix="knowledge-index-", suffix=".sqlite", dir=output_path.parent, delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    try:
        connection = sqlite3.connect(temporary_path)
        connection.execute("PRAGMA page_size = 4096")
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA locking_mode = EXCLUSIVE")
        connection.execute("PRAGMA auto_vacuum = NONE")
        connection.execute("PRAGMA application_id = 1093744203")
        connection.executescript(MIGRATION.read_text(encoding="utf-8"))
        for table in INDEX_TABLE_ORDER:
            table_rows = rows[table]
            if table_rows:
                placeholders = ",".join("?" for _ in table_rows[0])
                connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", table_rows)
        metadata = {
            "index_format_version": str(INDEX_FORMAT_VERSION),
            "migration_sha256": migration_sha256,
            "store_manifest_sha256": inventory["manifest"]["manifest_sha256"],
            "store_content_digest": inventory["content_digest"],
            "canonical_row_digest": canonical_digest,
        }
        connection.executemany("INSERT INTO metadata (key, value) VALUES (?, ?)", sorted(metadata.items()))
        connection.commit()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        require(not foreign_key_errors, f"SQLite foreign-key validation failed: {foreign_key_errors}")
        connection.execute("VACUUM")
        connection.close()
        database_sha256 = hash_file(temporary_path)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    index_manifest = finalize_document(
        {
            "schema": INDEX_SCHEMA,
            "format_version": INDEX_FORMAT_VERSION,
            "store_id": inventory["manifest"]["store_id"],
            "store_manifest_sha256": inventory["manifest"]["manifest_sha256"],
            "store_content_digest": inventory["content_digest"],
            "migration_sha256": migration_sha256,
            "canonical_row_digest": canonical_digest,
            "record_count": len(inventory["records"]),
            "object_count": len(inventory["objects"]),
            "sqlite_version": sqlite3.sqlite_version,
            "database_sha256": database_sha256,
            "calculation_ready": False,
            "no_submission_authorization": True,
        },
        "manifest_sha256",
    )
    contracts.write_json(manifest_path, index_manifest)
    return index_manifest


def validate_index_manifest(value: dict[str, Any]) -> None:
    fields = {
        "schema", "format_version", "store_id", "store_manifest_sha256", "store_content_digest",
        "migration_sha256", "canonical_row_digest", "record_count", "object_count", "sqlite_version",
        "database_sha256", "calculation_ready", "no_submission_authorization", "manifest_sha256",
    }
    contracts.exact_keys(value, fields, fields, "index manifest")
    require(value["schema"] == INDEX_SCHEMA, f"index manifest schema must be {INDEX_SCHEMA}")
    require(value["format_version"] == INDEX_FORMAT_VERSION, "unsupported index format version")
    contracts.identifier(value["store_id"], "index manifest.store_id")
    for field in ("store_manifest_sha256", "store_content_digest", "migration_sha256", "canonical_row_digest", "database_sha256", "manifest_sha256"):
        contracts.sha256(value[field], f"index manifest.{field}")
    require(isinstance(value["record_count"], int) and value["record_count"] >= 0, "index record_count is invalid")
    require(isinstance(value["object_count"], int) and value["object_count"] >= 0, "index object_count is invalid")
    contracts.string(value["sqlite_version"], "index manifest.sqlite_version")
    require(value["calculation_ready"] is False, "index cannot grant calculation readiness")
    require(value["no_submission_authorization"] is True, "index cannot grant submission authority")
    verify_document_hash(value, "manifest_sha256", "index manifest")


def verify_index(index_path: Path, inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    reject_symlink(index_path, "SQLite index")
    require(index_path.is_file(), f"SQLite index is missing: {index_path}")
    manifest_path = index_manifest_path(index_path)
    reject_symlink(manifest_path, "index manifest")
    require(manifest_path.is_file(), f"index manifest is missing: {manifest_path}")
    manifest = contracts.load_json(manifest_path)
    validate_index_manifest(manifest)
    require(MIGRATION.is_file(), f"SQLite migration is missing: {MIGRATION}")
    require(hash_file(MIGRATION) == manifest["migration_sha256"], "index migration binding is stale")
    require(hash_file(index_path) == manifest["database_sha256"], "SQLite index hash mismatch")
    if inventory is not None:
        require(manifest["store_manifest_sha256"] == inventory["manifest"]["manifest_sha256"], "index store-manifest binding is stale")
        require(manifest["store_content_digest"] == inventory["content_digest"], "index is stale relative to canonical store")
    connection = sqlite3.connect(f"file:{index_path.resolve()}?mode=ro", uri=True)
    metadata = dict(connection.execute("SELECT key, value FROM metadata ORDER BY key").fetchall())
    connection.close()
    for field in ("store_manifest_sha256", "store_content_digest", "migration_sha256", "canonical_row_digest"):
        require(metadata.get(field) == manifest[field], f"SQLite metadata mismatch for {field}")
    return manifest


def load_principal(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = contracts.load_json(path)
    fields = {"schema", "principal_id", "group_member", "projects", "confidential_record_ids"}
    contracts.exact_keys(value, fields, fields, "principal")
    require(value["schema"] == PRINCIPAL_SCHEMA, f"principal schema must be {PRINCIPAL_SCHEMA}")
    contracts.string(value["principal_id"], "principal.principal_id")
    require(type(value["group_member"]) is bool, "principal.group_member must be boolean")
    contracts.string_list(value["projects"], "principal.projects")
    contracts.string_list(value["confidential_record_ids"], "principal.confidential_record_ids")
    return value


def access_allowed(row: sqlite3.Row, principal: dict[str, Any] | None) -> bool:
    access_class = row["access_class"]
    if access_class == "public":
        return True
    if principal is None:
        return False
    permitted = set(json.loads(row["permitted_principals_json"]))
    principal_id = principal["principal_id"]
    if access_class == "group_internal":
        return principal["group_member"] is True
    if access_class == "project_restricted":
        return (
            principal_id in permitted
            or (
                principal["group_member"] is True
                and row["owner_project"] in set(principal["projects"])
            )
        )
    if access_class == "confidential_unpublished":
        return principal_id in permitted and row["record_id"] in set(principal["confidential_record_ids"])
    return False


def query_index(args: argparse.Namespace) -> dict[str, Any]:
    inventory = verify_store(Path(args.store))
    index_path = Path(args.index)
    manifest = verify_index(index_path, inventory)
    principal = load_principal(Path(args.principal) if args.principal else None)
    require(1 <= args.limit <= 1000, "query limit must be between 1 and 1000")
    require(bool(args.external_scheme) == bool(args.external_value), "external scheme and value must be supplied together")

    connection = sqlite3.connect(f"file:{index_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    record_rows = connection.execute("SELECT * FROM records ORDER BY record_type, record_id, revision_id").fetchall()
    aliases: dict[tuple[str, str, str], set[tuple[str, str]]] = {}
    for row in connection.execute("SELECT * FROM aliases ORDER BY record_type, record_id, revision_id, alias_type, alias_value"):
        aliases.setdefault((row[0], row[1], row[2]), set()).add((row[3], row[4]))
    external: dict[tuple[str, str, str], set[tuple[str, str]]] = {}
    for row in connection.execute("SELECT * FROM external_identifiers ORDER BY record_type, record_id, revision_id, scheme, identifier_value"):
        external.setdefault((row[0], row[1], row[2]), set()).add((row[3], row[4]))
    relations = {
        (row[0], row[1]): row[2]
        for row in connection.execute("SELECT record_id, revision_id, relation_type FROM links ORDER BY record_id, revision_id")
    }
    connection.close()

    allowed_results: list[dict[str, Any]] = []
    denied = 0
    for row in record_rows:
        key = (row["record_type"], row["record_id"], row["revision_id"])
        reasons: list[str] = []
        if args.registry != "all" and row["record_type"] != args.registry:
            continue
        reasons.append(f"registry={row['record_type']}")
        if args.record_id:
            if row["record_id"] != args.record_id:
                continue
            reasons.append("record_id_exact")
        if args.review_status:
            if row["review_status"] != args.review_status:
                continue
            reasons.append(f"review_status={args.review_status}")
        if args.access_class:
            if row["access_class"] != args.access_class:
                continue
            reasons.append(f"access_class={args.access_class}")
        if args.alias:
            matched = [item for item in aliases.get(key, set()) if item[1].casefold() == args.alias.casefold()]
            if not matched:
                continue
            reasons.append(f"alias_exact:{matched[0][0]}")
        if args.external_scheme:
            matched = [
                item for item in external.get(key, set())
                if item[0].casefold() == args.external_scheme.casefold()
                and item[1].casefold() == args.external_value.casefold()
            ]
            if not matched:
                continue
            reasons.append(f"external_exact:{matched[0][0]}")
        if args.relation_type:
            if row["record_type"] != "link" or relations.get((row["record_id"], row["revision_id"])) != args.relation_type:
                continue
            reasons.append(f"relation_type={args.relation_type}")
        if not access_allowed(row, principal):
            denied += 1
            continue
        allowed_results.append(
            {
                "record_type": row["record_type"],
                "record_id": row["record_id"],
                "revision_id": row["revision_id"],
                "payload_sha256": row["payload_sha256"],
                "review_status": row["review_status"],
                "access_class": row["access_class"],
                "match_reasons": reasons,
            }
        )
    total_allowed = len(allowed_results)
    return {
        "schema": "auto-g16-knowledge-query-result/1",
        "index_manifest_sha256": manifest["manifest_sha256"],
        "store_content_digest": inventory["content_digest"],
        "principal_mode": "public_only" if principal is None else "declared_offline_principal",
        "result_count": min(total_allowed, args.limit),
        "total_allowed_matches": total_allowed,
        "access_denied_matches": denied,
        "truncated": total_allowed > args.limit,
        "results": allowed_results[: args.limit],
        "calculation_ready": False,
        "no_submission_authorization": True,
    }


def verify_parent_artifact(snapshot: dict[str, Any], snapshot_path: Path, artifact_root: Path | None) -> dict[str, Any]:
    binding = snapshot["parent_reaction_intake"]
    relative = Path(binding["path"])
    require(not relative.is_absolute(), "snapshot parent path must be portable and relative")
    require(".." not in relative.parts, "snapshot parent path must not contain parent traversal")
    root_path = artifact_root or snapshot_path.parent
    reject_symlink(root_path, "snapshot artifact root")
    root = root_path.resolve()
    candidate = root / relative
    for parent in candidate.parents:
        if parent == root:
            break
        reject_symlink(parent, "snapshot parent directory")
    reject_symlink(candidate, "snapshot parent artifact")
    require(candidate.is_file(), f"snapshot parent artifact is missing: {candidate}")
    resolved = candidate.resolve()
    require(resolved.is_relative_to(root), "snapshot parent artifact escapes artifact root")
    require(resolved.stat().st_size == binding["size_bytes"], "snapshot parent artifact size drift")
    require(hash_file(resolved) == binding["sha256"], "snapshot parent artifact file hash drift")
    parent = contracts.load_json(resolved)
    require(parent.get("schema") == "gaussian-reaction-intake/1", "snapshot parent schema mismatch")
    require(parent.get("payload_sha256") == binding["payload_sha256"], "snapshot parent payload hash binding mismatch")
    require(contracts.payload_sha256(parent) == binding["payload_sha256"], "snapshot parent payload was modified after hashing")
    return {"path": str(resolved), "sha256": binding["sha256"], "payload_sha256": binding["payload_sha256"]}


def verify_snapshot(snapshot_path: Path, store_path: Path, artifact_root: Path | None) -> dict[str, Any]:
    reject_symlink(snapshot_path, "knowledge snapshot")
    snapshot = contracts.load_json(snapshot_path)
    contracts.validate_record(snapshot)
    require(snapshot["schema"] == "auto-g16-knowledge-snapshot/1", "verify-snapshot requires a knowledge snapshot")
    inventory = verify_store(store_path)
    canonical = resolve_ref(
        {
            "record_type": "snapshot",
            "record_id": snapshot["record_id"],
            "revision_id": snapshot["revision_id"],
            "payload_sha256": snapshot["payload_sha256"],
        },
        inventory["records"],
        "snapshot",
    )
    require(canonical is not None, "snapshot must resolve to a canonical store revision")
    validate_snapshot_against_records(snapshot, inventory["records"], "snapshot")
    parent = verify_parent_artifact(snapshot, snapshot_path, artifact_root)
    return {
        "schema": "auto-g16-knowledge-snapshot-verification/1",
        "snapshot_record_id": snapshot["record_id"],
        "snapshot_revision_id": snapshot["revision_id"],
        "snapshot_payload_sha256": snapshot["payload_sha256"],
        "dependency_digest": snapshot["dependency_digest"],
        "verified_record_count": len(snapshot["included_records"]),
        "store_content_digest": inventory["content_digest"],
        "parent_reaction_intake": parent,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }


def command_init_store(args: argparse.Namespace) -> None:
    manifest = init_store(Path(args.store), args.store_id, args.created_at)
    print(json.dumps({"store": args.store, **manifest}, ensure_ascii=False, sort_keys=True))


def command_verify_store(args: argparse.Namespace) -> None:
    inventory = verify_store(Path(args.store))
    print(
        json.dumps(
            {
                "valid": True,
                "store_id": inventory["manifest"]["store_id"],
                "record_count": len(inventory["records"]),
                "object_count": len(inventory["objects"]),
                "content_digest": inventory["content_digest"],
                "duplicate_candidates": inventory["duplicate_candidates"],
                "conflicts": inventory["conflicts"],
                "calculation_ready": False,
                "no_submission_authorization": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def command_rebuild_index(args: argparse.Namespace) -> None:
    manifest = rebuild_index(Path(args.store), Path(args.output))
    print(json.dumps({"index": args.output, **manifest}, ensure_ascii=False, sort_keys=True))


def command_query(args: argparse.Namespace) -> None:
    print(json.dumps(query_index(args), ensure_ascii=False, sort_keys=True))


def command_verify_snapshot(args: argparse.Namespace) -> None:
    result = verify_snapshot(
        Path(args.snapshot),
        Path(args.store),
        Path(args.artifact_root) if args.artifact_root else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def add_subparsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    init = subparsers.add_parser("init-store", help="Create an empty immutable knowledge-store layout")
    init.add_argument("store")
    init.add_argument("--store-id")
    init.add_argument("--created-at")
    init.set_defaults(func=command_init_store)

    verify = subparsers.add_parser("verify-store", help="Validate canonical records, objects, links, and snapshots")
    verify.add_argument("store")
    verify.set_defaults(func=command_verify_store)

    rebuild = subparsers.add_parser("rebuild-index", help="Build a fresh deterministic SQLite index")
    rebuild.add_argument("--store", required=True)
    rebuild.add_argument("--output", required=True)
    rebuild.set_defaults(func=command_rebuild_index)

    query = subparsers.add_parser("query", help="Run exact permission-filtered queries against a verified index")
    query.add_argument("--store", required=True)
    query.add_argument("--index", required=True)
    query.add_argument("--registry", choices=["all", "structure", "method", "source", "link", "snapshot"], default="all")
    query.add_argument("--record-id")
    query.add_argument("--alias")
    query.add_argument("--external-scheme")
    query.add_argument("--external-value")
    query.add_argument("--review-status", choices=sorted(contracts.REVIEW_STATUSES))
    query.add_argument("--access-class", choices=sorted(contracts.ACCESS_CLASSES))
    query.add_argument("--relation-type", choices=sorted(contracts.RELATION_TYPES))
    query.add_argument("--principal")
    query.add_argument("--limit", type=int, default=100)
    query.set_defaults(func=command_query)

    snapshot = subparsers.add_parser("verify-snapshot", help="Verify exact snapshot records and parent reaction intake")
    snapshot.add_argument("snapshot")
    snapshot.add_argument("--store", required=True)
    snapshot.add_argument("--artifact-root")
    snapshot.set_defaults(func=command_verify_snapshot)
