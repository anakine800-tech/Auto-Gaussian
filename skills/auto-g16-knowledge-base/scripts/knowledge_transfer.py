#!/usr/bin/env python3
"""Reviewed import and permission-aware export for the Auto-G16 W2 store."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import knowledge_base as contracts
import knowledge_store as store


IMPORT_PLAN_SCHEMA = "auto-g16-knowledge-import-plan/1"
TRANSFER_APPROVAL_SCHEMA = "auto-g16-knowledge-transfer-approval/1"
IMPORT_RESULT_SCHEMA = "auto-g16-knowledge-import-result/1"
EXPORT_PLAN_SCHEMA = "auto-g16-knowledge-export-plan/1"
EXPORT_MANIFEST_SCHEMA = "auto-g16-knowledge-export-manifest/1"


class TransferError(ValueError):
    """A reviewed transfer artifact or operation failed closed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TransferError(message)


def reject_symlink(path: Path, label: str) -> None:
    require(not path.is_symlink(), f"{label} must not be a symlink: {path}")


def file_binding(path: Path, base: Path) -> dict[str, Any]:
    reject_symlink(path, "source file")
    require(path.is_file(), f"source file is missing: {path}")
    resolved = path.resolve()
    return {
        "path": os.path.relpath(resolved, base.resolve()),
        "sha256": store.hash_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def resolve_bound_file(binding: dict[str, Any], artifact_path: Path, label: str) -> Path:
    relative = Path(binding["path"])
    require(not relative.is_absolute(), f"{label} path must be relative to its artifact")
    candidate = artifact_path.parent.resolve() / relative
    reject_symlink(candidate, label)
    require(candidate.is_file(), f"{label} is missing: {candidate}")
    resolved = candidate.resolve()
    require(resolved.stat().st_size == binding["size_bytes"], f"{label} size drift")
    require(store.hash_file(resolved) == binding["sha256"], f"{label} hash drift")
    return resolved


def transfer_hash(value: dict[str, Any], field: str) -> str:
    payload = copy.deepcopy(value)
    payload.pop(field, None)
    return contracts.sha256_data(payload)


def finalize_artifact(value: dict[str, Any], field: str) -> dict[str, Any]:
    value[field] = transfer_hash(value, field)
    return value


def verify_artifact_hash(value: dict[str, Any], field: str, label: str) -> None:
    contracts.sha256(value.get(field), f"{label}.{field}")
    require(value[field] == transfer_hash(value, field), f"{label} hash mismatch")


def exact(value: dict[str, Any], fields: set[str], label: str) -> None:
    contracts.exact_keys(value, fields, fields, label)


def require_outside_store(path: Path, root: Path, label: str) -> None:
    require(
        not path.resolve().is_relative_to(root.resolve()),
        f"{label} must remain outside the canonical store",
    )


def validate_binding(value: dict[str, Any], label: str) -> None:
    exact(value, {"path", "sha256", "size_bytes"}, label)
    contracts.string(value["path"], f"{label}.path")
    contracts.sha256(value["sha256"], f"{label}.sha256")
    require(isinstance(value["size_bytes"], int) and value["size_bytes"] >= 0, f"{label}.size_bytes is invalid")


def common_non_authority(value: dict[str, Any], label: str) -> None:
    require(value["calculation_ready"] is False, f"{label} cannot grant calculation readiness")
    require(value["no_submission_authorization"] is True, f"{label} cannot grant submission authority")


def validate_import_plan(value: dict[str, Any]) -> None:
    fields = {
        "schema", "plan_id", "created_at", "store_id", "store_manifest_sha256",
        "store_content_digest", "records", "objects", "review_state",
        "calculation_ready", "no_submission_authorization", "plan_sha256",
    }
    exact(value, fields, "import plan")
    require(value["schema"] == IMPORT_PLAN_SCHEMA, "unsupported import-plan schema")
    contracts.identifier(value["plan_id"], "import plan.plan_id")
    contracts.timestamp(value["created_at"], "import plan.created_at")
    contracts.identifier(value["store_id"], "import plan.store_id")
    for field in ("store_manifest_sha256", "store_content_digest"):
        contracts.sha256(value[field], f"import plan.{field}")
    require(value["review_state"] == "awaiting_review", "import plan must await review")
    require(isinstance(value["records"], list) and value["records"], "import plan requires records")
    destinations: set[str] = set()
    for index, item in enumerate(value["records"]):
        label = f"import plan.records[{index}]"
        exact(item, {"source", "record_type", "record_id", "revision_id", "payload_sha256", "destination"}, label)
        validate_binding(item["source"], f"{label}.source")
        require(item["record_type"] in store.STORE_RECORD_TYPES, f"{label}.record_type is invalid")
        contracts.identifier(item["record_id"], f"{label}.record_id")
        contracts.identifier(item["revision_id"], f"{label}.revision_id")
        contracts.sha256(item["payload_sha256"], f"{label}.payload_sha256")
        expected = f"records/{item['record_type']}/{item['record_id']}/{item['revision_id']}.json"
        require(item["destination"] == expected, f"{label}.destination is noncanonical")
        require(expected not in destinations, f"duplicate import destination: {expected}")
        destinations.add(expected)
    require(isinstance(value["objects"], list), "import plan.objects must be an array")
    object_hashes: set[str] = set()
    for index, item in enumerate(value["objects"]):
        label = f"import plan.objects[{index}]"
        exact(item, {"source", "sha256", "size_bytes", "media_type", "destination"}, label)
        validate_binding(item["source"], f"{label}.source")
        contracts.sha256(item["sha256"], f"{label}.sha256")
        require(item["source"]["sha256"] == item["sha256"], f"{label} source hash mismatch")
        require(item["source"]["size_bytes"] == item["size_bytes"], f"{label} source size mismatch")
        contracts.string(item["media_type"], f"{label}.media_type")
        expected = f"objects/sha256/{item['sha256'][:2]}/{item['sha256']}"
        require(item["destination"] == expected, f"{label}.destination is noncanonical")
        require(item["sha256"] not in object_hashes, f"duplicate planned object: {item['sha256']}")
        object_hashes.add(item["sha256"])
    common_non_authority(value, "import plan")
    verify_artifact_hash(value, "plan_sha256", "import plan")


def validate_approval(value: dict[str, Any], operation: str | None = None) -> None:
    fields = {
        "schema", "operation", "plan_schema", "plan_sha256", "decision", "reviewer",
        "reviewed_at", "notes", "calculation_ready", "no_submission_authorization",
        "approval_sha256",
    }
    exact(value, fields, "transfer approval")
    require(value["schema"] == TRANSFER_APPROVAL_SCHEMA, "unsupported transfer-approval schema")
    require(value["operation"] in {"import", "export"}, "approval operation is invalid")
    if operation:
        require(value["operation"] == operation, f"approval is not for {operation}")
    expected_schema = IMPORT_PLAN_SCHEMA if value["operation"] == "import" else EXPORT_PLAN_SCHEMA
    require(value["plan_schema"] == expected_schema, "approval plan schema mismatch")
    contracts.sha256(value["plan_sha256"], "approval.plan_sha256")
    require(value["decision"] in {"approved", "rejected"}, "approval decision is invalid")
    contracts.string(value["reviewer"], "approval.reviewer")
    contracts.timestamp(value["reviewed_at"], "approval.reviewed_at")
    contracts.string_list(value["notes"], "approval.notes")
    common_non_authority(value, "transfer approval")
    verify_artifact_hash(value, "approval_sha256", "transfer approval")


def validate_import_result(value: dict[str, Any]) -> None:
    fields = {
        "schema", "plan_sha256", "approval_sha256", "store_id",
        "previous_store_content_digest", "new_store_content_digest",
        "record_count_added", "object_count_added", "applied_destinations",
        "calculation_ready", "no_submission_authorization", "result_sha256",
    }
    exact(value, fields, "import result")
    require(value["schema"] == IMPORT_RESULT_SCHEMA, "unsupported import-result schema")
    for field in ("plan_sha256", "approval_sha256", "previous_store_content_digest", "new_store_content_digest"):
        contracts.sha256(value[field], f"import result.{field}")
    contracts.identifier(value["store_id"], "import result.store_id")
    for field in ("record_count_added", "object_count_added"):
        require(isinstance(value[field], int) and value[field] >= 0, f"import result.{field} is invalid")
    contracts.string_list(value["applied_destinations"], "import result.applied_destinations")
    common_non_authority(value, "import result")
    verify_artifact_hash(value, "result_sha256", "import result")


def parse_object_args(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        digest, separator, path = value.partition("=")
        require(separator == "=" and path, "--object must use SHA256=PATH")
        contracts.sha256(digest, "--object SHA-256")
        require(digest not in result, f"duplicate --object SHA-256: {digest}")
        result[digest] = Path(path)
    return result


def plan_import(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output)
    reject_symlink(output, "import plan")
    require(not output.exists(), f"refusing to overwrite import plan: {output}")
    inventory = store.verify_store(Path(args.store))
    require_outside_store(output, inventory["root"], "import plan")
    base = output.parent
    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    for path_text in args.record:
        path = Path(path_text)
        binding = file_binding(path, base)
        record = contracts.load_json(path)
        contracts.validate_record(record)
        require(path.read_bytes() == contracts.canonical_bytes(record), f"candidate record is not canonical JSON: {path}")
        key = store.record_key(record)
        require(key not in inventory["records"], f"record revision already exists: {key}")
        require(key not in candidates, f"duplicate candidate record revision: {key}")
        candidates[key] = record
        destination = f"records/{key[0]}/{key[1]}/{key[2]}.json"
        items.append({
            "source": binding, "record_type": key[0], "record_id": key[1],
            "revision_id": key[2], "payload_sha256": record["payload_sha256"],
            "destination": destination,
        })
    merged = dict(inventory["records"])
    merged.update(candidates)
    store.validate_cross_references(merged)

    provided = parse_object_args(args.object)
    candidate_refs = store.extract_object_refs(candidates)
    required: dict[str, dict[str, Any]] = {}
    for ref in candidate_refs:
        obj = ref["object"]
        if obj["storage_status"] == "lawful_local_object":
            existing = inventory["objects"].get(obj["sha256"])
            if existing and existing["present_local"]:
                require(existing["size_bytes"] == obj["size_bytes"], f"existing object size conflicts: {obj['sha256']}")
                require(existing["media_type"] == obj["media_type"], f"existing object media type conflicts: {obj['sha256']}")
            else:
                prior = required.get(obj["sha256"])
                if prior:
                    require(prior["size_bytes"] == obj["size_bytes"] and prior["media_type"] == obj["media_type"], f"candidate object metadata conflicts: {obj['sha256']}")
                required[obj["sha256"]] = obj
    require(set(provided) == set(required), "supplied objects must exactly match new lawful_local_object references")
    object_items: list[dict[str, Any]] = []
    for digest, obj in sorted(required.items()):
        binding = file_binding(provided[digest], base)
        require(binding["sha256"] == digest, f"object content hash mismatch: {digest}")
        require(binding["size_bytes"] == obj["size_bytes"], f"object size mismatch: {digest}")
        object_items.append({
            "source": binding, "sha256": digest, "size_bytes": obj["size_bytes"],
            "media_type": obj["media_type"],
            "destination": f"objects/sha256/{digest[:2]}/{digest}",
        })
    plan = finalize_artifact({
        "schema": IMPORT_PLAN_SCHEMA,
        "plan_id": args.plan_id,
        "created_at": args.created_at or store.utc_now(),
        "store_id": inventory["manifest"]["store_id"],
        "store_manifest_sha256": inventory["manifest"]["manifest_sha256"],
        "store_content_digest": inventory["content_digest"],
        "records": sorted(items, key=lambda item: item["destination"]),
        "objects": object_items,
        "review_state": "awaiting_review",
        "calculation_ready": False,
        "no_submission_authorization": True,
    }, "plan_sha256")
    validate_import_plan(plan)
    contracts.write_json(output, plan)
    return plan


def review_plan(args: argparse.Namespace, operation: str) -> dict[str, Any]:
    output = Path(args.output)
    reject_symlink(output, "transfer approval")
    require(not output.exists(), f"refusing to overwrite transfer approval: {output}")
    plan = contracts.load_json(Path(args.plan))
    if operation == "import":
        validate_import_plan(plan)
    else:
        validate_export_plan(plan)
    approval = finalize_artifact({
        "schema": TRANSFER_APPROVAL_SCHEMA,
        "operation": operation,
        "plan_schema": plan["schema"],
        "plan_sha256": plan["plan_sha256"],
        "decision": args.decision,
        "reviewer": args.reviewer,
        "reviewed_at": args.reviewed_at or store.utc_now(),
        "notes": args.note,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }, "approval_sha256")
    validate_approval(approval, operation)
    contracts.write_json(output, approval)
    return approval


def require_approved(plan: dict[str, Any], approval: dict[str, Any], operation: str) -> None:
    validate_approval(approval, operation)
    require(approval["plan_schema"] == plan["schema"], "approval plan schema drift")
    require(approval["plan_sha256"] == plan["plan_sha256"], "approval does not bind this plan")
    require(approval["decision"] == "approved", f"{operation} plan was not approved")


def exclusive_copy(source: Path, destination: Path) -> None:
    require(not destination.exists(), f"refusing to overwrite destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, destination.open("xb") as writer:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            writer.write(chunk)


def apply_import(args: argparse.Namespace) -> dict[str, Any]:
    result_path = Path(args.output)
    reject_symlink(result_path, "import result")
    require(not result_path.exists(), f"refusing to overwrite import result: {result_path}")
    plan_path = Path(args.plan)
    plan = contracts.load_json(plan_path)
    validate_import_plan(plan)
    approval = contracts.load_json(Path(args.approval))
    require_approved(plan, approval, "import")
    inventory = store.verify_store(Path(args.store))
    require_outside_store(result_path, inventory["root"], "import result")
    require(inventory["manifest"]["store_id"] == plan["store_id"], "import store ID drift")
    require(inventory["manifest"]["manifest_sha256"] == plan["store_manifest_sha256"], "import store manifest drift")
    require(inventory["content_digest"] == plan["store_content_digest"], "import store content drift")

    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    record_sources: list[tuple[Path, Path]] = []
    root = inventory["root"]
    for item in plan["records"]:
        source = resolve_bound_file(item["source"], plan_path, "planned record source")
        record = contracts.load_json(source)
        contracts.validate_record(record)
        require(source.read_bytes() == contracts.canonical_bytes(record), "planned record source is not canonical JSON")
        key = store.record_key(record)
        expected = (item["record_type"], item["record_id"], item["revision_id"])
        require(key == expected and record["payload_sha256"] == item["payload_sha256"], "planned record identity drift")
        destination = root / item["destination"]
        require(not destination.exists(), f"record destination appeared after planning: {destination}")
        records[key] = record
        record_sources.append((source, destination))
    merged = dict(inventory["records"])
    merged.update(records)
    store.validate_cross_references(merged)

    required_objects: dict[str, dict[str, Any]] = {}
    for ref in store.extract_object_refs(records):
        obj = ref["object"]
        if obj["storage_status"] != "lawful_local_object":
            continue
        existing = inventory["objects"].get(obj["sha256"])
        if existing and existing["present_local"]:
            require(
                existing["size_bytes"] == obj["size_bytes"]
                and existing["media_type"] == obj["media_type"],
                f"existing object metadata conflicts: {obj['sha256']}",
            )
        else:
            prior = required_objects.get(obj["sha256"])
            if prior:
                require(
                    prior["size_bytes"] == obj["size_bytes"]
                    and prior["media_type"] == obj["media_type"],
                    f"planned object metadata conflicts: {obj['sha256']}",
                )
            required_objects[obj["sha256"]] = obj
    require(
        {item["sha256"] for item in plan["objects"]} == set(required_objects),
        "planned objects do not exactly match new lawful_local_object references",
    )

    object_sources: list[tuple[Path, Path]] = []
    for item in plan["objects"]:
        required = required_objects[item["sha256"]]
        require(
            item["size_bytes"] == required["size_bytes"]
            and item["media_type"] == required["media_type"],
            f"planned object metadata drift: {item['sha256']}",
        )
        source = resolve_bound_file(item["source"], plan_path, "planned object source")
        destination = root / item["destination"]
        require(not destination.exists(), f"object destination appeared after planning: {destination}")
        object_sources.append((source, destination))
    for source, destination in object_sources:
        exclusive_copy(source, destination)
    for source, destination in record_sources:
        exclusive_copy(source, destination)
    final_inventory = store.verify_store(root)
    result = finalize_artifact({
        "schema": IMPORT_RESULT_SCHEMA,
        "plan_sha256": plan["plan_sha256"],
        "approval_sha256": approval["approval_sha256"],
        "store_id": plan["store_id"],
        "previous_store_content_digest": plan["store_content_digest"],
        "new_store_content_digest": final_inventory["content_digest"],
        "record_count_added": len(record_sources),
        "object_count_added": len(object_sources),
        "applied_destinations": [item["destination"] for item in plan["objects"] + plan["records"]],
        "calculation_ready": False,
        "no_submission_authorization": True,
    }, "result_sha256")
    validate_import_result(result)
    contracts.write_json(result_path, result)
    return result


def record_access_allowed(record: dict[str, Any], principal: dict[str, Any] | None) -> bool:
    access = record["access"]
    if access["class"] == "public":
        return True
    if principal is None:
        return False
    principal_id = principal["principal_id"]
    if access["class"] == "group_internal":
        return principal["group_member"] is True
    if access["class"] == "project_restricted":
        return principal_id in access["permitted_principals"] or (
            principal["group_member"] is True and access["owner_project"] in principal["projects"]
        )
    return principal_id in access["permitted_principals"] and record["record_id"] in principal["confidential_record_ids"]


def local_refs(record: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    record_type = store.record_key(record)[0]
    if record_type == "structure":
        for field in ("parent_identity", "parent_state"):
            if record.get(field):
                refs.append(record[field])
        for representation in record["representations"]:
            refs.extend(representation["supporting_record_refs"])
    elif record_type == "method":
        for fact in record["protocol"].values():
            refs.extend(anchor["source_record"] for anchor in fact["source_anchor_refs"])
        for field in ("supporting_source_refs", "benchmark_record_refs", "failure_record_refs"):
            refs.extend(record["evidence"][field])
    elif record_type == "link":
        refs.extend((record["source"], record["target"]))
        refs.extend(anchor["source_record"] for anchor in record["source_anchors"])
        refs.extend(record["evidence_record_refs"])
    elif record_type == "snapshot":
        refs.extend(record["included_records"])
        refs.extend(item["record_ref"] for item in record["selection_decisions"])
    return [ref for ref in refs if ref["record_type"] in store.STORE_RECORD_TYPES]


def redacted_envelope(record: dict[str, Any], reason: str) -> dict[str, Any]:
    key = store.record_key(record)
    envelope = {
        "schema": "auto-g16-knowledge-redacted-record/1",
        "record_type": key[0],
        "record_id": key[1],
        "revision_id": key[2],
        "canonical_payload_sha256": record["payload_sha256"],
        "canonical_schema": record["schema"],
        "review_status": record["review"]["status"],
        "access_class": record["access"]["class"],
        "redaction_reason": reason,
        "scientific_content_included": False,
        "objects_included": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    fields = {
        "schema", "record_type", "record_id", "revision_id",
        "canonical_payload_sha256", "canonical_schema", "review_status",
        "access_class", "redaction_reason", "scientific_content_included",
        "objects_included", "calculation_ready", "no_submission_authorization",
    }
    exact(envelope, fields, "redacted record")
    require(envelope["scientific_content_included"] is False and envelope["objects_included"] is False, "redacted record cannot contain content")
    common_non_authority(envelope, "redacted record")
    return envelope


def validate_export_manifest(value: dict[str, Any]) -> None:
    fields = {
        "schema", "plan_sha256", "approval_sha256", "store_id",
        "store_content_digest", "principal_mode", "files",
        "excluded_access_count", "excluded_no_export_count", "objects_included",
        "calculation_ready", "no_submission_authorization", "manifest_sha256",
    }
    exact(value, fields, "export manifest")
    require(value["schema"] == EXPORT_MANIFEST_SCHEMA, "unsupported export-manifest schema")
    for field in ("plan_sha256", "approval_sha256", "store_content_digest"):
        contracts.sha256(value[field], f"export manifest.{field}")
    contracts.identifier(value["store_id"], "export manifest.store_id")
    require(value["principal_mode"] in {"public_only", "declared_offline_principal"}, "export manifest principal mode is invalid")
    require(isinstance(value["files"], list), "export manifest.files must be an array")
    for index, item in enumerate(value["files"]):
        label = f"export manifest.files[{index}]"
        exact(item, {"path", "sha256", "size_bytes", "action"}, label)
        contracts.string(item["path"], f"{label}.path")
        contracts.sha256(item["sha256"], f"{label}.sha256")
        require(isinstance(item["size_bytes"], int) and item["size_bytes"] >= 0, f"{label}.size_bytes is invalid")
        require(item["action"] in {"full_record", "metadata_redacted"}, f"{label}.action is invalid")
    for field in ("excluded_access_count", "excluded_no_export_count"):
        require(isinstance(value[field], int) and value[field] >= 0, f"export manifest.{field} is invalid")
    require(value["objects_included"] is False, "export manifest cannot include binary objects")
    common_non_authority(value, "export manifest")
    verify_artifact_hash(value, "manifest_sha256", "export manifest")


def validate_export_plan(value: dict[str, Any]) -> None:
    fields = {
        "schema", "plan_id", "created_at", "store_id", "store_manifest_sha256",
        "store_content_digest", "index_manifest_sha256", "principal", "selection",
        "destination", "items", "excluded_access_count", "excluded_no_export_count",
        "objects_included", "review_state", "calculation_ready",
        "no_submission_authorization", "plan_sha256",
    }
    exact(value, fields, "export plan")
    require(value["schema"] == EXPORT_PLAN_SCHEMA, "unsupported export-plan schema")
    contracts.identifier(value["plan_id"], "export plan.plan_id")
    contracts.timestamp(value["created_at"], "export plan.created_at")
    contracts.identifier(value["store_id"], "export plan.store_id")
    for field in ("store_manifest_sha256", "store_content_digest", "index_manifest_sha256"):
        contracts.sha256(value[field], f"export plan.{field}")
    exact(value["principal"], {"mode", "source"}, "export plan.principal")
    require(value["principal"]["mode"] in {"public_only", "declared_offline_principal"}, "export principal mode is invalid")
    if value["principal"]["source"] is not None:
        validate_binding(value["principal"]["source"], "export plan.principal.source")
    exact(value["selection"], {"registry", "record_ids"}, "export plan.selection")
    require(value["selection"]["registry"] in {"all", *store.STORE_RECORD_TYPES}, "export registry is invalid")
    contracts.string_list(value["selection"]["record_ids"], "export plan.selection.record_ids")
    contracts.string(value["destination"], "export plan.destination")
    require(isinstance(value["items"], list), "export plan.items must be an array")
    for index, item in enumerate(value["items"]):
        label = f"export plan.items[{index}]"
        exact(item, {"record_type", "record_id", "revision_id", "payload_sha256", "action", "reason", "destination", "export_payload_sha256"}, label)
        require(item["record_type"] in store.STORE_RECORD_TYPES, f"{label}.record_type is invalid")
        contracts.identifier(item["record_id"], f"{label}.record_id")
        contracts.identifier(item["revision_id"], f"{label}.revision_id")
        contracts.sha256(item["payload_sha256"], f"{label}.payload_sha256")
        require(item["action"] in {"full_record", "metadata_redacted"}, f"{label}.action is invalid")
        contracts.string(item["reason"], f"{label}.reason")
        contracts.string(item["destination"], f"{label}.destination")
        directory = "full" if item["action"] == "full_record" else "redacted"
        expected = f"records/{directory}/{item['record_type']}/{item['record_id']}/{item['revision_id']}.json"
        require(item["destination"] == expected, f"{label}.destination is noncanonical")
        contracts.sha256(item["export_payload_sha256"], f"{label}.export_payload_sha256")
    for field in ("excluded_access_count", "excluded_no_export_count"):
        require(isinstance(value[field], int) and value[field] >= 0, f"export plan.{field} is invalid")
    require(value["objects_included"] is False, "W2 export cannot include binary objects")
    require(value["review_state"] == "awaiting_review", "export plan must await review")
    common_non_authority(value, "export plan")
    verify_artifact_hash(value, "plan_sha256", "export plan")


def plan_export(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output)
    reject_symlink(output, "export plan")
    require(not output.exists(), f"refusing to overwrite export plan: {output}")
    destination = Path(args.destination)
    reject_symlink(destination, "export destination")
    require(not destination.exists(), f"export destination already exists: {destination}")
    inventory = store.verify_store(Path(args.store))
    require_outside_store(output, inventory["root"], "export plan")
    require_outside_store(destination, inventory["root"], "export destination")
    index_manifest = store.verify_index(Path(args.index), inventory)
    principal_path = Path(args.principal) if args.principal else None
    principal = store.load_principal(principal_path)
    principal_binding = file_binding(principal_path, output.parent) if principal_path else None
    selected_ids = set(args.record_id)
    items: list[dict[str, Any]] = []
    excluded_access = 0
    excluded_policy = 0
    for key, record in sorted(inventory["records"].items()):
        if args.registry != "all" and key[0] != args.registry:
            continue
        if selected_ids and key[1] not in selected_ids:
            continue
        if not record_access_allowed(record, principal):
            excluded_access += 1
            continue
        policy = record["access"]["export_policy"]
        if policy == "no_export":
            excluded_policy += 1
            continue
        action = "full_record"
        reason = "record policy permits full export"
        if policy == "metadata_redacted":
            action = "metadata_redacted"
            reason = "record export policy requires metadata redaction"
        else:
            for ref in local_refs(record):
                target = inventory["records"][store.record_ref_key(ref)]
                if not record_access_allowed(target, principal) or target["access"]["export_policy"] != "full":
                    action = "metadata_redacted"
                    reason = "record dependency is not fully exportable to this principal"
                    break
        if action == "full_record":
            exported = record
            relative = f"records/full/{key[0]}/{key[1]}/{key[2]}.json"
        else:
            exported = redacted_envelope(record, reason)
            relative = f"records/redacted/{key[0]}/{key[1]}/{key[2]}.json"
        items.append({
            "record_type": key[0], "record_id": key[1], "revision_id": key[2],
            "payload_sha256": record["payload_sha256"], "action": action,
            "reason": reason, "destination": relative,
            "export_payload_sha256": contracts.sha256_data(exported),
        })
    if selected_ids:
        known = {key[1] for key in inventory["records"]}
        require(selected_ids <= known, f"requested record IDs are unknown: {sorted(selected_ids - known)}")
    plan = finalize_artifact({
        "schema": EXPORT_PLAN_SCHEMA,
        "plan_id": args.plan_id,
        "created_at": args.created_at or store.utc_now(),
        "store_id": inventory["manifest"]["store_id"],
        "store_manifest_sha256": inventory["manifest"]["manifest_sha256"],
        "store_content_digest": inventory["content_digest"],
        "index_manifest_sha256": index_manifest["manifest_sha256"],
        "principal": {"mode": "public_only" if principal is None else "declared_offline_principal", "source": principal_binding},
        "selection": {"registry": args.registry, "record_ids": sorted(selected_ids)},
        "destination": os.path.relpath(destination.resolve(), output.parent.resolve()),
        "items": items,
        "excluded_access_count": excluded_access,
        "excluded_no_export_count": excluded_policy,
        "objects_included": False,
        "review_state": "awaiting_review",
        "calculation_ready": False,
        "no_submission_authorization": True,
    }, "plan_sha256")
    validate_export_plan(plan)
    contracts.write_json(output, plan)
    return plan


def apply_export(args: argparse.Namespace) -> dict[str, Any]:
    plan_path = Path(args.plan)
    plan = contracts.load_json(plan_path)
    validate_export_plan(plan)
    approval = contracts.load_json(Path(args.approval))
    require_approved(plan, approval, "export")
    inventory = store.verify_store(Path(args.store))
    require(inventory["manifest"]["store_id"] == plan["store_id"], "export store ID drift")
    require(inventory["manifest"]["manifest_sha256"] == plan["store_manifest_sha256"], "export store manifest drift")
    require(inventory["content_digest"] == plan["store_content_digest"], "export store content drift")
    index_manifest = store.verify_index(Path(args.index), inventory)
    require(index_manifest["manifest_sha256"] == plan["index_manifest_sha256"], "export index binding drift")
    principal = None
    if plan["principal"]["source"] is not None:
        principal_path = resolve_bound_file(plan["principal"]["source"], plan_path, "planned principal declaration")
        principal = store.load_principal(principal_path)
    destination_path = plan_path.parent.resolve() / plan["destination"]
    reject_symlink(destination_path, "export destination")
    destination = destination_path.resolve()
    require_outside_store(destination, inventory["root"], "export destination")
    require(not destination.exists(), f"refusing to overwrite export destination: {destination}")

    prepared: list[tuple[dict[str, Any], bytes]] = []
    for item in plan["items"]:
        record = inventory["records"][(item["record_type"], item["record_id"], item["revision_id"])]
        require(record["payload_sha256"] == item["payload_sha256"], "planned export record hash drift")
        require(record_access_allowed(record, principal), "planned export access no longer allowed")
        if item["action"] == "full_record":
            require(record["access"]["export_policy"] == "full", "full export policy drift")
            for ref in local_refs(record):
                target = inventory["records"][store.record_ref_key(ref)]
                require(record_access_allowed(target, principal) and target["access"]["export_policy"] == "full", "full export dependency policy drift")
            exported = record
        else:
            exported = redacted_envelope(record, item["reason"])
        require(contracts.sha256_data(exported) == item["export_payload_sha256"], "planned export payload drift")
        prepared.append((item, contracts.canonical_bytes(exported)))

    destination.mkdir(parents=True)
    written: list[dict[str, Any]] = []
    for item, data in prepared:
        target = destination / item["destination"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(data)
        written.append({"path": item["destination"], "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "action": item["action"]})
    manifest = finalize_artifact({
        "schema": EXPORT_MANIFEST_SCHEMA,
        "plan_sha256": plan["plan_sha256"],
        "approval_sha256": approval["approval_sha256"],
        "store_id": plan["store_id"],
        "store_content_digest": plan["store_content_digest"],
        "principal_mode": plan["principal"]["mode"],
        "files": written,
        "excluded_access_count": plan["excluded_access_count"],
        "excluded_no_export_count": plan["excluded_no_export_count"],
        "objects_included": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }, "manifest_sha256")
    validate_export_manifest(manifest)
    contracts.write_json(destination / "export-manifest.json", manifest)
    return manifest


def command_plan_import(args: argparse.Namespace) -> None:
    print(json.dumps({"output": args.output, **plan_import(args)}, ensure_ascii=False, sort_keys=True))


def command_review_import(args: argparse.Namespace) -> None:
    print(json.dumps({"output": args.output, **review_plan(args, "import")}, ensure_ascii=False, sort_keys=True))


def command_apply_import(args: argparse.Namespace) -> None:
    print(json.dumps({"output": args.output, **apply_import(args)}, ensure_ascii=False, sort_keys=True))


def command_plan_export(args: argparse.Namespace) -> None:
    print(json.dumps({"output": args.output, **plan_export(args)}, ensure_ascii=False, sort_keys=True))


def command_review_export(args: argparse.Namespace) -> None:
    print(json.dumps({"output": args.output, **review_plan(args, "export")}, ensure_ascii=False, sort_keys=True))


def command_apply_export(args: argparse.Namespace) -> None:
    print(json.dumps({"applied": True, **apply_export(args)}, ensure_ascii=False, sort_keys=True))


def add_subparsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    plan_in = subparsers.add_parser("plan-import", help="Plan immutable records and lawful local objects without writing the store")
    plan_in.add_argument("--store", required=True)
    plan_in.add_argument("--record", action="append", required=True)
    plan_in.add_argument("--object", action="append", default=[], help="Exact SHA256=PATH for each new lawful local object")
    plan_in.add_argument("--plan-id", required=True)
    plan_in.add_argument("--created-at")
    plan_in.add_argument("--output", required=True)
    plan_in.set_defaults(func=command_plan_import)

    review_in = subparsers.add_parser("review-import", help="Approve or reject one exact import plan")
    add_review_arguments(review_in)
    review_in.set_defaults(func=command_review_import)

    apply_in = subparsers.add_parser("apply-import", help="Apply one exact approved import plan without overwrite")
    apply_in.add_argument("--store", required=True)
    apply_in.add_argument("--plan", required=True)
    apply_in.add_argument("--approval", required=True)
    apply_in.add_argument("--output", required=True)
    apply_in.set_defaults(func=command_apply_import)

    plan_out = subparsers.add_parser("plan-export", help="Plan a permission-aware full or metadata-redacted export")
    plan_out.add_argument("--store", required=True)
    plan_out.add_argument("--index", required=True)
    plan_out.add_argument("--destination", required=True)
    plan_out.add_argument("--registry", choices=["all", *sorted(store.STORE_RECORD_TYPES)], default="all")
    plan_out.add_argument("--record-id", action="append", default=[])
    plan_out.add_argument("--principal")
    plan_out.add_argument("--plan-id", required=True)
    plan_out.add_argument("--created-at")
    plan_out.add_argument("--output", required=True)
    plan_out.set_defaults(func=command_plan_export)

    review_out = subparsers.add_parser("review-export", help="Approve or reject one exact export plan")
    add_review_arguments(review_out)
    review_out.set_defaults(func=command_review_export)

    apply_out = subparsers.add_parser("apply-export", help="Apply one exact approved redacted export without overwrite")
    apply_out.add_argument("--store", required=True)
    apply_out.add_argument("--index", required=True)
    apply_out.add_argument("--plan", required=True)
    apply_out.add_argument("--approval", required=True)
    apply_out.set_defaults(func=command_apply_export)


def add_review_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", required=True)
    parser.add_argument("--decision", choices=["approved", "rejected"], required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at")
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--output", required=True)
