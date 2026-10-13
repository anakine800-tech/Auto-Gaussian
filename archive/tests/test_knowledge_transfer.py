#!/usr/bin/env python3
"""Offline tests for reviewed W2 knowledge import and redacted export."""

from __future__ import annotations

import hashlib
import json
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
CONTRACTS = ROOT / "contracts" / "knowledge-base"
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


def artifact_hash(value: dict[str, object], field: str) -> str:
    copy = dict(value)
    copy.pop(field, None)
    return hashlib.sha256(canonical_bytes(copy)).hexdigest()


class KnowledgeTransferTests(unittest.TestCase):
    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], cwd=ROOT, check=check,
            capture_output=True, text=True,
        )

    def init_store(self, store: Path) -> None:
        self.run_cli(
            "init-store", str(store), "--store-id", "fixture_store",
            "--created-at", "2026-07-15T00:00:00+00:00",
        )

    def install_record(self, store: Path, record: dict[str, object]) -> Path:
        record_type = SCHEMA_TYPES[str(record["schema"])]
        target = store / "records" / record_type / str(record["record_id"]) / f"{record['revision_id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_bytes(record))
        return target

    def install_all_records(self, store: Path) -> None:
        for source in sorted(RECORDS.glob("*.json")):
            self.install_record(store, load(source))

    def build_index(self, store: Path, name: str = "index.sqlite") -> Path:
        index = store / "indexes" / name
        self.run_cli("rebuild-index", "--store", str(store), "--output", str(index))
        return index

    def write_principal(self, path: Path) -> None:
        path.write_text(json.dumps({
            "schema": "auto-g16-knowledge-principal/1",
            "principal_id": "fixture_reviewer",
            "group_member": True,
            "projects": ["fixture_project"],
            "confidential_record_ids": [],
        }), encoding="utf-8")

    def test_transfer_contracts_are_closed_and_non_authorizing(self) -> None:
        expected = {
            "import-plan.schema.json": "auto-g16-knowledge-import-plan/1",
            "transfer-approval.schema.json": "auto-g16-knowledge-transfer-approval/1",
            "import-result.schema.json": "auto-g16-knowledge-import-result/1",
            "export-plan.schema.json": "auto-g16-knowledge-export-plan/1",
            "redacted-record.schema.json": "auto-g16-knowledge-redacted-record/1",
            "export-manifest.schema.json": "auto-g16-knowledge-export-manifest/1",
        }
        for filename, schema_name in expected.items():
            with self.subTest(contract=filename):
                contract = load(CONTRACTS / filename)
                self.assertFalse(contract["additionalProperties"])
                self.assertEqual(contract["properties"]["schema"]["const"], schema_name)
                self.assertEqual(contract["properties"]["calculation_ready"]["const"], False)
                self.assertEqual(contract["properties"]["no_submission_authorization"]["const"], True)

    def make_lawful_candidate(self, root: Path) -> tuple[Path, Path, str]:
        candidate = load(RECORDS / "structure-identity.json")
        candidate["record_id"] = "fixture_imported_identity"
        candidate["revision_id"] = "fixture_imported_identity_r001"
        candidate["aliases"][0]["value"] = "Imported reviewed fixture"
        content = b"C\n"
        digest = hashlib.sha256(content).hexdigest()
        candidate["representations"][0]["object"].update({
            "sha256": digest,
            "size_bytes": len(content),
            "storage_status": "lawful_local_object",
        })
        candidate["payload_sha256"] = payload_hash(candidate)
        record_path = root / "candidate.json"
        object_path = root / "candidate.smi"
        record_path.write_bytes(canonical_bytes(candidate))
        object_path.write_bytes(content)
        return record_path, object_path, digest

    def review(self, operation: str, plan: Path, approval: Path, decision: str = "approved") -> None:
        self.run_cli(
            f"review-{operation}", "--plan", str(plan), "--decision", decision,
            "--reviewer", "fixture_reviewer", "--reviewed-at", "2026-07-15T02:00:00+00:00",
            "--note", "Reviewed exact transfer fixture.", "--output", str(approval),
        )

    def test_plan_review_apply_import_ingests_exact_record_and_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            stale_index = self.build_index(store, "before.sqlite")
            record_path, object_path, digest = self.make_lawful_candidate(root)
            plan = root / "import-plan.json"
            self.run_cli(
                "plan-import", "--store", str(store), "--record", str(record_path),
                "--object", f"{digest}={object_path}", "--plan-id", "fixture_import_plan",
                "--created-at", "2026-07-15T01:00:00+00:00", "--output", str(plan),
            )
            self.assertEqual(json.loads(self.run_cli("verify-store", str(store)).stdout)["record_count"], 0)

            rejected = root / "rejected.json"
            self.review("import", plan, rejected, "rejected")
            failed = self.run_cli(
                "apply-import", "--store", str(store), "--plan", str(plan),
                "--approval", str(rejected), "--output", str(root / "rejected-result.json"), check=False,
            )
            self.assertIn("plan was not approved", failed.stderr)
            self.assertEqual(json.loads(self.run_cli("verify-store", str(store)).stdout)["record_count"], 0)

            approval = root / "approval.json"
            result = root / "result.json"
            self.review("import", plan, approval)
            report = json.loads(self.run_cli(
                "apply-import", "--store", str(store), "--plan", str(plan),
                "--approval", str(approval), "--output", str(result),
            ).stdout)
            self.assertEqual(report["record_count_added"], 1)
            self.assertEqual(report["object_count_added"], 1)
            verified = json.loads(self.run_cli("verify-store", str(store)).stdout)
            self.assertEqual((verified["record_count"], verified["object_count"]), (1, 1))
            self.assertTrue((store / "objects" / "sha256" / digest[:2] / digest).is_file())
            stale = self.run_cli(
                "query", "--store", str(store), "--index", str(stale_index), check=False,
            )
            self.assertIn("index is stale", stale.stderr)

    def test_import_rechecks_sources_approval_store_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            record_path, object_path, digest = self.make_lawful_candidate(root)
            plan = root / "plan.json"
            approval = root / "approval.json"
            self.run_cli(
                "plan-import", "--store", str(store), "--record", str(record_path),
                "--object", f"{digest}={object_path}", "--plan-id", "fixture_drift_plan",
                "--output", str(plan),
            )
            self.review("import", plan, approval)
            object_path.write_bytes(b"tampered\n")
            failed = self.run_cli(
                "apply-import", "--store", str(store), "--plan", str(plan),
                "--approval", str(approval), "--output", str(root / "result.json"), check=False,
            )
            self.assertIn("planned object source size drift", failed.stderr)
            self.assertEqual(json.loads(self.run_cli("verify-store", str(store)).stdout)["record_count"], 0)

            extra_plan = load(plan)
            extra_plan["plan_sha256"] = "0" * 64
            plan.write_bytes(canonical_bytes(extra_plan))
            failed = self.run_cli(
                "apply-import", "--store", str(store), "--plan", str(plan),
                "--approval", str(approval), "--output", str(root / "result2.json"), check=False,
            )
            self.assertIn("import plan hash mismatch", failed.stderr)

    def test_import_rejects_unreferenced_object_and_artifacts_inside_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            record_path, object_path, digest = self.make_lawful_candidate(root)
            failed = self.run_cli(
                "plan-import", "--store", str(store), "--record", str(record_path),
                "--object", f"{digest}={object_path}", "--plan-id", "fixture_inside_store",
                "--output", str(store / "indexes" / "plan.json"), check=False,
            )
            self.assertIn("must remain outside the canonical store", failed.stderr)

            plan = root / "plan.json"
            self.run_cli(
                "plan-import", "--store", str(store), "--record", str(record_path),
                "--object", f"{digest}={object_path}", "--plan-id", "fixture_extra_object",
                "--output", str(plan),
            )
            extra_path = root / "extra.bin"
            extra_path.write_bytes(b"unreferenced\n")
            extra_digest = hashlib.sha256(extra_path.read_bytes()).hexdigest()
            forged = load(plan)
            forged["objects"].append({
                "source": {"path": extra_path.name, "sha256": extra_digest, "size_bytes": extra_path.stat().st_size},
                "sha256": extra_digest,
                "size_bytes": extra_path.stat().st_size,
                "media_type": "application/octet-stream",
                "destination": f"objects/sha256/{extra_digest[:2]}/{extra_digest}",
            })
            forged["plan_sha256"] = artifact_hash(forged, "plan_sha256")
            forged_path = root / "forged-plan.json"
            forged_path.write_bytes(canonical_bytes(forged))
            approval = root / "approval.json"
            self.review("import", forged_path, approval)
            failed = self.run_cli(
                "apply-import", "--store", str(store), "--plan", str(forged_path),
                "--approval", str(approval), "--output", str(root / "result.json"), check=False,
            )
            self.assertIn("do not exactly match", failed.stderr)
            self.assertEqual(json.loads(self.run_cli("verify-store", str(store)).stdout)["object_count"], 0)

    def test_import_rejects_noncanonical_record_serialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            record_path, object_path, digest = self.make_lawful_candidate(root)
            record_path.write_text(json.dumps(load(record_path), indent=2), encoding="utf-8")
            failed = self.run_cli(
                "plan-import", "--store", str(store), "--record", str(record_path),
                "--object", f"{digest}={object_path}", "--plan-id", "fixture_noncanonical",
                "--output", str(root / "plan.json"), check=False,
            )
            self.assertIn("not canonical JSON", failed.stderr)

    def test_public_export_is_reviewed_full_json_and_excludes_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            self.install_all_records(store)
            index = self.build_index(store)
            plan = root / "export-plan.json"
            destination = root / "public-export"
            report = json.loads(self.run_cli(
                "plan-export", "--store", str(store), "--index", str(index),
                "--destination", str(destination), "--plan-id", "fixture_public_export",
                "--created-at", "2026-07-15T03:00:00+00:00", "--output", str(plan),
            ).stdout)
            self.assertEqual(len(report["items"]), 2)
            self.assertEqual(report["excluded_access_count"], 6)
            self.assertTrue(all(item["action"] == "full_record" for item in report["items"]))
            self.assertFalse(destination.exists())
            approval = root / "export-approval.json"
            self.review("export", plan, approval)
            manifest = json.loads(self.run_cli(
                "apply-export", "--store", str(store), "--index", str(index),
                "--plan", str(plan), "--approval", str(approval),
            ).stdout)
            self.assertEqual(len(manifest["files"]), 2)
            self.assertFalse(manifest["objects_included"])
            self.assertFalse((destination / "objects").exists())
            exported = load(destination / "records" / "full" / "method" / "fixture_reported_method" / "fixture_reported_method_r001.json")
            self.assertEqual(exported["payload_sha256"], load(RECORDS / "method-reported.json")["payload_sha256"])

    def test_authorized_export_redacts_policy_limited_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            self.install_all_records(store)
            index = self.build_index(store)
            principal = root / "principal.json"
            self.write_principal(principal)
            plan = root / "export-plan.json"
            destination = root / "reviewed-export"
            report = json.loads(self.run_cli(
                "plan-export", "--store", str(store), "--index", str(index),
                "--destination", str(destination), "--principal", str(principal),
                "--plan-id", "fixture_reviewed_export", "--output", str(plan),
            ).stdout)
            actions = [item["action"] for item in report["items"]]
            self.assertEqual((actions.count("full_record"), actions.count("metadata_redacted")), (4, 4))
            approval = root / "approval.json"
            self.review("export", plan, approval)
            self.run_cli(
                "apply-export", "--store", str(store), "--index", str(index),
                "--plan", str(plan), "--approval", str(approval),
            )
            redacted = load(destination / "records" / "redacted" / "snapshot" / "fixture_study_snapshot" / "fixture_study_snapshot_r001.json")
            self.assertFalse(redacted["scientific_content_included"])
            self.assertNotIn("included_records", redacted)
            self.assertNotIn("permitted_principals", redacted)

    def test_no_export_is_excluded_and_dependency_downgrades_full_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            identity = load(RECORDS / "structure-identity.json")
            identity["access"]["export_policy"] = "no_export"
            identity["payload_sha256"] = payload_hash(identity)
            state = load(RECORDS / "structure-state.json")
            state["parent_identity"]["payload_sha256"] = identity["payload_sha256"]
            state["access"]["export_policy"] = "full"
            state["payload_sha256"] = payload_hash(state)
            self.install_record(store, identity)
            self.install_record(store, state)
            index = self.build_index(store)
            principal = root / "principal.json"
            self.write_principal(principal)
            plan = root / "plan.json"
            destination = root / "export"
            report = json.loads(self.run_cli(
                "plan-export", "--store", str(store), "--index", str(index),
                "--destination", str(destination), "--principal", str(principal),
                "--record-id", str(state["record_id"]), "--plan-id", "fixture_dependency_export",
                "--output", str(plan),
            ).stdout)
            self.assertEqual(report["items"][0]["action"], "metadata_redacted")
            self.assertIn("dependency", report["items"][0]["reason"])

            no_export_plan = root / "no-export-plan.json"
            no_export_destination = root / "no-export"
            no_export = json.loads(self.run_cli(
                "plan-export", "--store", str(store), "--index", str(index),
                "--destination", str(no_export_destination), "--principal", str(principal),
                "--record-id", str(identity["record_id"]), "--plan-id", "fixture_no_export",
                "--output", str(no_export_plan),
            ).stdout)
            self.assertEqual(no_export["items"], [])
            self.assertEqual(no_export["excluded_no_export_count"], 1)

    def test_export_rechecks_approval_principal_store_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.init_store(store)
            self.install_all_records(store)
            index = self.build_index(store)
            principal = root / "principal.json"
            self.write_principal(principal)
            plan = root / "plan.json"
            destination = root / "export"
            self.run_cli(
                "plan-export", "--store", str(store), "--index", str(index),
                "--destination", str(destination), "--principal", str(principal),
                "--plan-id", "fixture_export_drift", "--output", str(plan),
            )
            rejected = root / "rejected.json"
            self.review("export", plan, rejected, "rejected")
            failed = self.run_cli(
                "apply-export", "--store", str(store), "--index", str(index),
                "--plan", str(plan), "--approval", str(rejected), check=False,
            )
            self.assertIn("plan was not approved", failed.stderr)
            self.assertFalse(destination.exists())

            approval = root / "approval.json"
            self.review("export", plan, approval)
            declaration = load(principal)
            declaration["projects"] = []
            principal.write_text(json.dumps(declaration), encoding="utf-8")
            failed = self.run_cli(
                "apply-export", "--store", str(store), "--index", str(index),
                "--plan", str(plan), "--approval", str(approval), check=False,
            )
            self.assertIn("planned principal declaration", failed.stderr)
            self.assertFalse(destination.exists())

            original = load(plan)
            original["items"][0]["destination"] = "../../escaped.json"
            original["plan_sha256"] = artifact_hash(original, "plan_sha256")
            traversal = root / "traversal-plan.json"
            traversal.write_bytes(canonical_bytes(original))
            failed = self.run_cli(
                "review-export", "--plan", str(traversal), "--decision", "approved",
                "--reviewer", "fixture_reviewer", "--output", str(root / "traversal-approval.json"),
                check=False,
            )
            self.assertIn("destination is noncanonical", failed.stderr)

    def test_transfer_code_remains_offline(self) -> None:
        code = (SKILL / "scripts" / "knowledge_transfer.py").read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "import socket", "requests", "paramiko", "qsub", "qdel"):
            self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
