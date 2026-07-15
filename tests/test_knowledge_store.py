#!/usr/bin/env python3
"""Offline W2B-1 tests for the immutable knowledge store and derived index."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "auto-g16-knowledge-base"
SCRIPT = SKILL / "scripts" / "knowledge_base.py"
RECORDS = ROOT / "tests" / "fixtures" / "knowledge_base" / "records"
SCHEMA_TYPES = {
    "auto-g16-structure-record/1": "structure",
    "auto-g16-method-record/1": "method",
    "auto-g16-source-record/1": "source",
    "auto-g16-knowledge-link/1": "link",
    "auto-g16-knowledge-snapshot/1": "snapshot",
}


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def payload_hash(value: dict[str, object]) -> str:
    copy = dict(value)
    copy.pop("payload_sha256", None)
    return hashlib.sha256(canonical_bytes(copy)).hexdigest()


class KnowledgeStoreTests(unittest.TestCase):
    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            check=check,
            capture_output=True,
            text=True,
        )

    def init_store(self, root: Path) -> None:
        self.run_cli(
            "init-store", str(root), "--store-id", "fixture_store",
            "--created-at", "2026-07-15T00:00:00+00:00",
        )

    def install_records(self, store: Path) -> None:
        for source in sorted(RECORDS.glob("*.json")):
            record = load(source)
            record_type = SCHEMA_TYPES[str(record["schema"])]
            target = store / "records" / record_type / str(record["record_id"]) / f"{record['revision_id']}.json"
            target.parent.mkdir(parents=True)
            shutil.copy2(source, target)

    def create_full_store(self, root: Path) -> None:
        self.init_store(root)
        self.install_records(root)

    def test_store_code_is_offline_and_migration_is_versioned(self) -> None:
        store_code = (SKILL / "scripts" / "knowledge_store.py").read_text(encoding="utf-8")
        migration = (SKILL / "scripts" / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "import socket", "requests", "paramiko", "qsub", "qdel"):
            self.assertNotIn(forbidden, store_code)
        self.assertIn("CREATE TABLE records", migration)
        self.assertIn("PRAGMA foreign_keys = ON", migration)
        self.assertNotIn("DROP TABLE", migration)

    def test_full_fixture_store_verifies_all_cross_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "store"
            self.create_full_store(store)
            report = json.loads(self.run_cli("verify-store", str(store)).stdout)
            self.assertTrue(report["valid"])
            self.assertEqual(report["record_count"], 8)
            self.assertEqual(report["object_count"], 2)
            self.assertFalse(report["calculation_ready"])
            self.assertTrue(report["no_submission_authorization"])

    def test_init_refuses_nonempty_store_and_store_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nonempty = root / "nonempty"
            nonempty.mkdir()
            (nonempty / "owned.txt").write_text("keep", encoding="utf-8")
            failed = self.run_cli("init-store", str(nonempty), check=False)
            self.assertIn("refusing to initialize non-empty", failed.stderr)

            store = root / "store"
            self.init_store(store)
            os.symlink(store / "records" / "source", store / "records" / "source_link")
            failed = self.run_cli("verify-store", str(store), check=False)
            self.assertIn("must not be a symlink", failed.stderr)

    def test_parent_revision_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "store"
            self.create_full_store(store)
            identity_path = next((store / "records" / "structure" / "fixture_boron_catalyst").glob("*.json"))
            identity = load(identity_path)
            identity["aliases"][0]["value"] = "Changed reviewed identity"
            identity["payload_sha256"] = payload_hash(identity)
            identity_path.write_bytes(canonical_bytes(identity))
            failed = self.run_cli("verify-store", str(store), check=False)
            self.assertIn("payload hash mismatch", failed.stderr)

    def test_content_addressed_object_is_verified_and_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "store"
            self.init_store(store)
            record = load(RECORDS / "structure-identity.json")
            content = b"reviewed fixture object\n"
            digest = hashlib.sha256(content).hexdigest()
            obj = record["representations"][0]["object"]
            obj.update({"sha256": digest, "size_bytes": len(content), "storage_status": "lawful_local_object"})
            record["payload_sha256"] = payload_hash(record)
            target = store / "records" / "structure" / str(record["record_id"]) / f"{record['revision_id']}.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(canonical_bytes(record))
            object_path = store / "objects" / "sha256" / digest[:2] / digest
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(content)
            self.run_cli("verify-store", str(store))
            object_path.write_bytes(b"tampered fixture object\n")
            failed = self.run_cli("verify-store", str(store), check=False)
            self.assertIn("object content hash mismatch", failed.stderr)

    def test_index_rebuild_is_deterministic_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "store"
            self.create_full_store(store)
            first = store / "indexes" / "first.sqlite"
            second = store / "indexes" / "second.sqlite"
            one = json.loads(self.run_cli("rebuild-index", "--store", str(store), "--output", str(first)).stdout)
            two = json.loads(self.run_cli("rebuild-index", "--store", str(store), "--output", str(second)).stdout)
            self.assertEqual(one["canonical_row_digest"], two["canonical_row_digest"])
            self.assertEqual(one["database_sha256"], two["database_sha256"])
            failed = self.run_cli("rebuild-index", "--store", str(store), "--output", str(first), check=False)
            self.assertIn("refusing to overwrite existing index", failed.stderr)

    def test_queries_are_exact_permission_filtered_and_fail_on_stale_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.create_full_store(store)
            index = store / "indexes" / "index.sqlite"
            self.run_cli("rebuild-index", "--store", str(store), "--output", str(index))

            public = json.loads(self.run_cli("query", "--store", str(store), "--index", str(index)).stdout)
            self.assertEqual(public["result_count"], 2)
            self.assertEqual(public["access_denied_matches"], 6)

            principal = root / "principal.json"
            principal.write_text(json.dumps({
                "schema": "auto-g16-knowledge-principal/1",
                "principal_id": "fixture_reviewer",
                "group_member": True,
                "projects": ["fixture_project"],
                "confidential_record_ids": [],
            }), encoding="utf-8")
            allowed = json.loads(self.run_cli(
                "query", "--store", str(store), "--index", str(index), "--principal", str(principal),
            ).stdout)
            self.assertEqual(allowed["result_count"], 8)

            doi = json.loads(self.run_cli(
                "query", "--store", str(store), "--index", str(index),
                "--external-scheme", "doi", "--external-value", "10.5555/AUTO.G16.FIXTURE",
            ).stdout)
            self.assertEqual([item["record_id"] for item in doi["results"]], ["fixture_article"])

            extra = load(RECORDS / "source-article.json")
            extra["record_id"] = "fixture_extra_article"
            extra["revision_id"] = "fixture_extra_article_r001"
            extra["external_identifiers"] = []
            extra["payload_sha256"] = payload_hash(extra)
            target = store / "records" / "source" / str(extra["record_id"]) / f"{extra['revision_id']}.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(canonical_bytes(extra))
            failed = self.run_cli("query", "--store", str(store), "--index", str(index), check=False)
            self.assertIn("index is stale", failed.stderr)

    def test_confidential_query_requires_both_record_grant_and_principal_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            record = load(RECORDS / "structure-identity.json")
            record["access"] = {
                "class": "confidential_unpublished",
                "owner_project": "fixture_project",
                "permitted_principals": ["fixture_reviewer"],
                "export_policy": "metadata_redacted",
            }
            record["payload_sha256"] = payload_hash(record)
            target = store / "records" / "structure" / str(record["record_id"]) / f"{record['revision_id']}.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(canonical_bytes(record))
            index = store / "indexes" / "index.sqlite"
            self.run_cli("rebuild-index", "--store", str(store), "--output", str(index))

            principal = root / "principal.json"
            declaration = {
                "schema": "auto-g16-knowledge-principal/1",
                "principal_id": "fixture_reviewer",
                "group_member": True,
                "projects": ["fixture_project"],
                "confidential_record_ids": [],
            }
            principal.write_text(json.dumps(declaration), encoding="utf-8")
            denied = json.loads(self.run_cli(
                "query", "--store", str(store), "--index", str(index), "--principal", str(principal),
            ).stdout)
            self.assertEqual(denied["result_count"], 0)
            self.assertEqual(denied["access_denied_matches"], 1)

            declaration["confidential_record_ids"] = [record["record_id"]]
            principal.write_text(json.dumps(declaration), encoding="utf-8")
            allowed = json.loads(self.run_cli(
                "query", "--store", str(store), "--index", str(index), "--principal", str(principal),
            ).stdout)
            self.assertEqual(allowed["result_count"], 1)

    def test_snapshot_binds_exact_records_and_parent_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.create_full_store(store)
            parent = {
                "schema": "gaussian-reaction-intake/1",
                "study_id": "fixture_reaction_study",
                "payload_sha256": None,
            }
            parent["payload_sha256"] = payload_hash(parent)
            parent_path = root / "reaction-intake.json"
            parent_path.write_bytes(canonical_bytes(parent))

            snapshot = load(RECORDS / "knowledge-snapshot.json")
            snapshot["revision_id"] = "fixture_study_snapshot_r002"
            snapshot["parent_reaction_intake"] = {
                "schema": "gaussian-reaction-intake/1",
                "path": parent_path.name,
                "sha256": hashlib.sha256(parent_path.read_bytes()).hexdigest(),
                "size_bytes": parent_path.stat().st_size,
                "payload_sha256": parent["payload_sha256"],
            }
            dependencies = sorted(
                snapshot["included_records"],
                key=lambda item: (item["record_type"], item["record_id"], item["revision_id"]),
            )
            snapshot["dependency_digest"] = hashlib.sha256(canonical_bytes(dependencies)).hexdigest()
            snapshot["payload_sha256"] = payload_hash(snapshot)
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_bytes(canonical_bytes(snapshot))
            canonical_snapshot = store / "records" / "snapshot" / str(snapshot["record_id"]) / f"{snapshot['revision_id']}.json"
            canonical_snapshot.write_bytes(snapshot_path.read_bytes())
            report = json.loads(self.run_cli(
                "verify-snapshot", str(snapshot_path), "--store", str(store), "--artifact-root", str(root),
            ).stdout)
            self.assertEqual(report["verified_record_count"], 7)
            self.assertEqual(report["parent_reaction_intake"]["payload_sha256"], parent["payload_sha256"])

            modified = dict(snapshot)
            modified["redactions"] = ["Modified outside the canonical store."]
            modified["payload_sha256"] = payload_hash(modified)
            modified_path = root / "modified-snapshot.json"
            modified_path.write_bytes(canonical_bytes(modified))
            failed = self.run_cli(
                "verify-snapshot", str(modified_path), "--store", str(store), "--artifact-root", str(root), check=False,
            )
            self.assertIn("snapshot payload hash mismatch", failed.stderr)

            parent["study_id"] = "tampered_study"
            parent_path.write_bytes(canonical_bytes(parent))
            failed = self.run_cli(
                "verify-snapshot", str(snapshot_path), "--store", str(store), "--artifact-root", str(root), check=False,
            )
            self.assertIn("parent artifact size drift", failed.stderr)


if __name__ == "__main__":
    unittest.main()
