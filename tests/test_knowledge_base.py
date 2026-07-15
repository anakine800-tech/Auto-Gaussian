#!/usr/bin/env python3
"""Offline acceptance tests for the W2 Auto-G16 knowledge base."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "auto-g16-knowledge-base"
SCRIPT = SKILL / "scripts" / "knowledge_base.py"
SCHEMAS = ROOT / "contracts" / "knowledge-base"
OBJECT_FIXTURE = ROOT / "tests" / "fixtures" / "knowledge_base" / "ethanol.smi"
W1_SCRIPT = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "reaction_workflow.py"
W1_FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow"
SPEC = importlib.util.spec_from_file_location("knowledge_base", SCRIPT)
assert SPEC and SPEC.loader
KB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KB)


class KnowledgeBaseTests(unittest.TestCase):
    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            check=check,
            capture_output=True,
            text=True,
        )

    def test_all_commands_expose_help(self) -> None:
        for command in (
            "validate",
            "finalize",
            "init-store",
            "import",
            "import-object",
            "rebuild",
            "verify-index",
            "query",
            "export",
            "snapshot",
            "verify-snapshot",
        ):
            with self.subTest(command=command):
                result = self.run_cli(command, "--help")
                self.assertIn("usage:", result.stdout)

    def common(
        self,
        record_type: str,
        logical_id: str,
        *,
        review_status: str = "reviewed",
        access_class: str = "public",
        project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        reviewed = review_status in {"reviewed", "reviewed_with_limits"}
        return {
            "schema": KB.SCHEMAS[record_type],
            "record_type": record_type,
            "logical_id": logical_id,
            "revision_id": f"{logical_id}_r001",
            "revision": 1,
            "created_at": "2026-07-15T00:00:00Z",
            "created_by": "fixture_curator",
            "review_status": review_status,
            "reviewed_by": "fixture_reviewer" if reviewed else None,
            "reviewed_at": "2026-07-15T01:00:00Z" if reviewed else None,
            "review_notes": ["Frozen public offline acceptance fixture."],
            "access": {
                "class": access_class,
                "project_ids": project_ids or [],
                "license": "fixture-metadata-only",
                "storage_status": "metadata_only",
            },
            "provenance": [
                {
                    "kind": "frozen_fixture",
                    "source": "tests/test_knowledge_base.py",
                    "locator": logical_id,
                    "sha256": None,
                }
            ],
            "aliases": [],
            "external_identifiers": [],
            "uncertainties": [],
            "blockers": [],
            "supersedes": None,
            "link_ids": [],
            "data": {},
            "payload_sha256": "",
            "calculation_ready": False,
            "no_submission_authorization": True,
        }

    def finalize(self, value: dict[str, Any]) -> dict[str, Any]:
        return KB.finalize_draft(value)

    def write_record(self, root: Path, value: dict[str, Any]) -> Path:
        record = self.finalize(value)
        path = root / f"{record['revision_id']}.json"
        path.write_bytes(KB.canonical_bytes(record))
        return path

    def commit_records(
        self,
        root: Path,
        store: Path,
        paths: list[Path],
        stem: str,
    ) -> dict[str, Any]:
        dry_run = root / f"{stem}-dry-run.json"
        commit_report = root / f"{stem}-commit.json"
        KB.import_records(store, paths, dry_run, commit=False)
        return KB.import_records(
            store,
            paths,
            commit_report,
            commit=True,
            approved_dry_run=dry_run,
        )

    def structure(
        self,
        object_ref: dict[str, Any],
        *,
        logical_id: str = "structure_ethanol_neutral",
        identity_id: str = "identity_ethanol",
        state_id: str = "state_ethanol_neutral_singlet",
        review_status: str = "reviewed",
    ) -> dict[str, Any]:
        value = self.common("structure", logical_id, review_status=review_status)
        value["aliases"] = ["ethanol", "ethyl alcohol"]
        value["external_identifiers"] = [{"scheme": "inchikey", "value": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"}]
        value["data"] = {
            "preferred_name": "ethanol, neutral singlet",
            "identity_id": identity_id,
            "state_id": state_id,
            "roles": ["solvent", "reference_compound"],
            "formula": "C2H6O",
            "formal_charge": 0,
            "multiplicity": 1,
            "component_count": 1,
            "protonation": "neutral parent",
            "salt_or_solvate": "none",
            "stereochemistry": "achiral constitution",
            "coordination_state": None,
            "representations": [
                {
                    "format": "smiles",
                    "object": object_ref,
                    "atom_order_sha256": None,
                    "review_scope": "constitution and neutral state only",
                    "geometry_provenance": "not a 3D geometry",
                    "limitations": ["SMILES does not authorize a Cartesian geometry."],
                }
            ],
            "ownership": {"owner": "public_fixture", "project": None, "sample_reference": None},
        }
        return value

    def method(
        self,
        *,
        logical_id: str = "method_fixture_opt_freq",
        review_status: str = "reviewed_with_limits",
        access_class: str = "project_restricted",
        project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        value = self.common(
            "method",
            logical_id,
            review_status=review_status,
            access_class=access_class,
            project_ids=project_ids or (["project_alpha"] if access_class == "project_restricted" else []),
        )
        value["aliases"] = ["fixture closed-shell Opt/Freq"]
        value["uncertainties"] = ["Fixture demonstrates contract completeness, not scientific accuracy."]
        value["data"] = {
            "name": "Frozen closed-shell Opt/Freq fixture protocol",
            "classification": "group_internal",
            "program": "Gaussian",
            "program_version": "syntax fixture only",
            "calculation_family": "minimum optimization and harmonic frequency",
            "protocol": {
                "functional": "fixture-functional",
                "dispersion": "explicitly none in fixture",
                "solvent_model": "gas phase fixture",
                "relativistic_treatment": "not applicable to H/C/O scope",
                "grid": "fixture-grid",
                "scf": "fixture-scf-policy",
                "optimization": "fixture-minimum-optimization-policy",
                "frequency": "analytic harmonic frequencies",
                "ts": "not in scope",
                "irc": "not in scope",
                "single_point_relationship": "no separate single point",
                "thermochemistry": "298.15 K ideal-gas fixture; no low-frequency correction",
            },
            "basis_by_element": {"C": "fixture-basis", "H": "fixture-basis", "O": "fixture-basis"},
            "scope": {
                "elements": ["C", "H", "O"],
                "catalyst_classes": [],
                "reaction_classes": ["offline contract fixture only"],
                "state_types": ["closed-shell singlet"],
                "job_stages": ["minimum", "frequency"],
                "exclusions": ["transition metals", "TS", "IRC", "method recommendation"],
            },
            "benchmarks": [],
            "failure_modes": ["No scientific benchmark; never promote beyond fixture scope."],
        }
        return value

    def source(
        self,
        *,
        logical_id: str = "source_fixture_book",
        doi: str | None = None,
    ) -> dict[str, Any]:
        value = self.common("source", logical_id)
        identifiers = [{"scheme": "isbn", "value": "978-0-00-000000-0"}]
        if doi:
            identifiers.append({"scheme": "doi", "value": doi})
        value["external_identifiers"] = copy.deepcopy(identifiers)
        value["data"] = {
            "source_type": "book_chapter",
            "title": "Frozen Scientific Curation Fixture",
            "authors_or_editors": ["A. Fixture"],
            "year": 2026,
            "publisher": "Public Fixture Press",
            "journal_or_book": "Audited Offline Knowledge",
            "volume": None,
            "issue": None,
            "edition": "1st edition",
            "chapter": "Chapter 2",
            "pages_or_article": "pp. 10-12",
            "identifiers": identifiers,
            "stable_url": None,
            "accessed_at": "2026-07-15T00:00:00Z",
            "anchors": [{"kind": "page", "locator": "page 11, fixture table 1"}],
            "relationships": [],
            "local_objects": [],
            "extracted_claims": [
                {
                    "claim_type": "fixture_method_description",
                    "paraphrase": "The fixture protocol is presented only to test record separation.",
                    "anchor": "page 11, fixture table 1",
                    "reviewer_interpretation": "Not a recommendation and not a real literature claim.",
                    "status": "source_reports",
                }
            ],
        }
        return value

    def link(self, method: dict[str, Any], source: dict[str, Any], *, public: bool = False) -> dict[str, Any]:
        access_class = "public" if public else "project_restricted"
        projects = [] if public else ["project_alpha"]
        value = self.common("link", "link_method_fixture_source", access_class=access_class, project_ids=projects)
        value["data"] = {
            "link_type": "method_reported_in_source",
            "source": KB.record_ref(method),
            "target": KB.record_ref(source),
            "evidence_mode": "direct",
            "anchors": ["page 11, fixture table 1"],
            "scope": "Contract fixture only; no method applicability claim.",
            "uncertainty": "No uncertainty within the synthetic fixture scope.",
            "mismatches": ["Synthetic fixture, not scientific evidence."],
        }
        return value

    def parent_intake(self, root: Path) -> tuple[Path, dict[str, str]]:
        path = root / "parent-intake.json"
        value = {
            "schema": "gaussian-reaction-intake/1",
            "intake_id": "fixture_intake",
            "calculation_ready": False,
            "no_submission_authorization": True,
            "payload_sha256": "",
        }
        value["payload_sha256"] = KB.payload_sha256(value)
        path.write_bytes(KB.canonical_bytes(value))
        return path, {
            "path": path.name,
            "sha256": KB.sha256_file(path),
            "payload_sha256": value["payload_sha256"],
        }

    def snapshot_request(
        self,
        root: Path,
        parent_ref: dict[str, str],
        records: list[dict[str, Any]],
    ) -> Path:
        grouped: dict[str, list[str]] = {}
        for record in records:
            grouped.setdefault(record["record_type"], []).append(record["revision_id"])
        value = {
            "schema": "auto-g16-knowledge-snapshot-request/1",
            "study_id": "study_w2_fixture",
            "parent_reaction_intake": parent_ref,
            "queries": [
                {
                    "registry": record_type,
                    "query": f"reviewed {record_type} fixture",
                    "selected_revision_ids": sorted(revision_ids),
                    "excluded_decisions": [],
                }
                for record_type, revision_ids in sorted(grouped.items())
            ],
            "selected_revision_ids": sorted(record["revision_id"] for record in records),
            "redactions": ["Records outside project_alpha were not exported."],
            "unresolved_gaps": ["No TS precedent was selected."],
            "contradictions": [],
            "author": "fixture_curator",
            "reviewer": "fixture_reviewer",
            "created_at": "2026-07-15T02:00:00Z",
            "review_status": "reviewed_with_limits",
            "access": {
                "class": "project_restricted",
                "project_ids": ["project_alpha"],
                "license": "fixture-metadata-only",
                "storage_status": "metadata_only",
            },
        }
        path = root / "snapshot-request.json"
        path.write_bytes(KB.canonical_bytes(value))
        return path

    def populated_store(self, root: Path) -> tuple[Path, list[dict[str, Any]]]:
        store = root / "store"
        KB.ensure_store(store, create=True)
        object_dry_run = root / "object-dry-run.json"
        object_arguments = {
            "media_type": "chemical/x-daylight-smiles",
            "license_name": "public fixture",
            "access_class": "public",
            "storage_status": "public_redistributable",
            "project_ids": [],
        }
        KB.import_object(
            store,
            OBJECT_FIXTURE,
            object_dry_run,
            **object_arguments,
            commit=False,
        )
        object_result = KB.import_object(
            store,
            OBJECT_FIXTURE,
            root / "object-commit.json",
            **object_arguments,
            commit=True,
            approved_dry_run=object_dry_run,
        )
        structure = self.finalize(self.structure(object_result["object"]))
        method = self.finalize(self.method())
        source = self.finalize(self.source(doi="10.5555/frozen.fixture"))
        link = self.finalize(self.link(method, source))
        paths = []
        for record in (structure, method, source, link):
            path = root / f"{record['revision_id']}.json"
            path.write_bytes(KB.canonical_bytes(record))
            paths.append(path)
        self.commit_records(root, store, paths, "records")
        return store, [structure, method, source, link]

    def test_skill_metadata_and_five_closed_schema_entry_points(self) -> None:
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertNotIn("TODO", skill)
        self.assertIn("name: auto-g16-knowledge-base", skill)
        self.assertIn("calculation_ready: false", skill)
        self.assertIn('display_name: "Auto-G16 Knowledge Base"', metadata)
        root_schema = json.loads((SCHEMAS / "record.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(len(root_schema["oneOf"]), 5)
        for name in ("structure", "method", "source", "link", "snapshot"):
            entry = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(entry["$ref"], f"record.schema.json#/$defs/{name}Record")
        for data_name in ("structureData", "methodData", "sourceData", "linkData", "snapshotData"):
            self.assertFalse(root_schema["$defs"][data_name]["additionalProperties"])
        self.assertTrue(
            {
                "literature_reported",
                "group_internal",
                "benchmark_candidate",
                "validated_within_scope",
                "blocked",
                "deprecated",
            }
            <= KB.METHOD_CLASSES
        )

    def test_finalize_validate_and_semantic_refusals(self) -> None:
        object_ref = {
            "sha256": KB.sha256_file(OBJECT_FIXTURE),
            "size_bytes": OBJECT_FIXTURE.stat().st_size,
            "media_type": "chemical/x-daylight-smiles",
            "original_name": OBJECT_FIXTURE.name,
        }
        structure = self.finalize(self.structure(object_ref))
        self.assertEqual(structure["payload_sha256"], KB.payload_sha256(structure))
        self.assertFalse(structure["calculation_ready"])
        self.assertTrue(structure["no_submission_authorization"])

        incomplete = self.method(access_class="public", project_ids=[])
        incomplete["data"]["basis_by_element"].pop("O")
        with self.assertRaisesRegex(KB.KnowledgeError, "basis/ECP coverage"):
            self.finalize(incomplete)

        book = self.source()
        book["data"]["edition"] = None
        with self.assertRaisesRegex(KB.KnowledgeError, "requires an edition"):
            self.finalize(book)

        si = self.source(logical_id="source_fixture_si")
        si["data"]["source_type"] = "supporting_information"
        si["data"]["relationships"] = []
        with self.assertRaisesRegex(KB.KnowledgeError, "supplement_to"):
            self.finalize(si)

        tampered = copy.deepcopy(structure)
        tampered["calculation_ready"] = True
        tampered["payload_sha256"] = KB.payload_sha256(tampered)
        with self.assertRaisesRegex(KB.KnowledgeError, "calculation_ready"):
            KB.validate_record(tampered)

    def test_dry_run_object_and_record_imports_never_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            self.run_cli("init-store", str(store))
            dry = root / "object-dry.json"
            commit = root / "object-commit.json"
            object_args = (
                "import-object", str(store), str(OBJECT_FIXTURE),
                "--media-type", "chemical/x-daylight-smiles",
                "--license", "public fixture",
                "--access-class", "public",
                "--storage-status", "public_redistributable",
            )
            self.run_cli(*object_args, "--report", str(dry))
            dry_data = json.loads(dry.read_text(encoding="utf-8"))
            self.assertEqual(dry_data["status"], "would_commit")
            self.assertFalse((store / dry_data["store_path"]).exists())
            unapproved = self.run_cli(
                *object_args,
                "--report",
                str(root / "object-unapproved.json"),
                "--commit",
                check=False,
            )
            self.assertNotEqual(unapproved.returncode, 0)
            self.assertIn("approved-dry-run", unapproved.stderr)
            self.assertFalse((store / dry_data["store_path"]).exists())
            self.run_cli(
                *object_args,
                "--report",
                str(commit),
                "--commit",
                "--approved-dry-run",
                str(dry),
            )
            commit_data = json.loads(commit.read_text(encoding="utf-8"))
            self.assertTrue((store / commit_data["store_path"]).is_file())
            self.assertTrue((store / commit_data["metadata_path"]).is_file())
            self.assertEqual(commit_data["access"]["storage_status"], "public_redistributable")

            draft_path = root / "structure-draft.json"
            draft_path.write_bytes(KB.canonical_bytes(self.structure(commit_data["object"])))
            record_path = root / "structure-final.json"
            self.run_cli("finalize", str(draft_path), "--output", str(record_path))
            record_dry = root / "record-dry.json"
            self.run_cli("import", str(store), str(record_path), "--report", str(record_dry))
            self.assertEqual(json.loads(record_dry.read_text())["results"][0]["action"], "would_add_new_revision")
            self.assertFalse(KB.record_path(store, KB.load_json(record_path)).exists())
            unapproved_record = self.run_cli(
                "import",
                str(store),
                str(record_path),
                "--report",
                str(root / "record-unapproved.json"),
                "--commit",
                check=False,
            )
            self.assertNotEqual(unapproved_record.returncode, 0)
            self.assertIn("approved-dry-run", unapproved_record.stderr)
            self.assertFalse(KB.record_path(store, KB.load_json(record_path)).exists())
            record_commit = root / "record-commit.json"
            self.run_cli(
                "import",
                str(store),
                str(record_path),
                "--report",
                str(record_commit),
                "--commit",
                "--approved-dry-run",
                str(record_dry),
            )
            self.assertTrue(KB.record_path(store, KB.load_json(record_path)).is_file())
            failed = self.run_cli("import", str(store), str(record_path), "--report", str(record_commit), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("refusing to overwrite", failed.stderr)

    def test_conflict_import_emits_ledger_and_never_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store, records = self.populated_store(root)
            duplicate = self.finalize(self.source(logical_id="source_duplicate_doi", doi="10.5555/frozen.fixture"))
            duplicate_path = root / "duplicate.json"
            duplicate_path.write_bytes(KB.canonical_bytes(duplicate))
            report = root / "conflict-report.json"
            failed = self.run_cli("import", str(store), str(duplicate_path), "--report", str(report), check=False)
            self.assertNotEqual(failed.returncode, 0)
            ledger = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(ledger["results"][0]["action"], "refuse_conflict")
            self.assertIn("source_doi_duplicate", ledger["results"][0]["conflicts"])
            self.assertFalse(KB.record_path(store, duplicate).exists())
            self.assertEqual(len(KB.load_store_records(store)), len(records))

            canonical_structure = next(item for item in records if item["record_type"] == "structure")
            structure_duplicate = self.finalize(
                self.structure(
                    canonical_structure["data"]["representations"][0]["object"],
                    logical_id="structure_ethanol_duplicate",
                )
            )
            structure_path = root / "structure-duplicate.json"
            structure_path.write_bytes(KB.canonical_bytes(structure_duplicate))
            structure_report = root / "structure-conflict-report.json"
            failed = self.run_cli(
                "import",
                str(store),
                str(structure_path),
                "--report",
                str(structure_report),
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            structure_ledger = json.loads(structure_report.read_text(encoding="utf-8"))
            self.assertIn(
                "structure_identity_state_duplicate",
                structure_ledger["results"][0]["conflicts"],
            )

    def test_deterministic_rebuild_and_permission_negative_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store, _ = self.populated_store(root)
            first = root / "index-one.sqlite3"
            second = root / "index-two.sqlite3"
            one = KB.rebuild_index(store, first)
            two = KB.rebuild_index(store, second)
            self.assertEqual(one["database_fingerprint"], two["database_fingerprint"])
            self.assertEqual(KB.sha256_file(first), KB.sha256_file(second))
            self.assertEqual(KB.verify_index(store, first)["status"], "current")

            public = root / "public.json"
            KB.query_index(first, public, registry="method", query="fixture", statuses={"reviewed_with_limits"}, grants={"public"}, project_ids=set())
            self.assertEqual(json.loads(public.read_text())["result_count"], 0)
            no_project = root / "no-project.json"
            KB.query_index(first, no_project, registry="method", query="fixture", statuses={"reviewed_with_limits"}, grants={"public", "project_restricted"}, project_ids=set())
            self.assertEqual(json.loads(no_project.read_text())["result_count"], 0)
            wrong_project = root / "wrong-project.json"
            KB.query_index(first, wrong_project, registry="method", query="fixture", statuses={"reviewed_with_limits"}, grants={"public", "project_restricted"}, project_ids={"project_beta"})
            self.assertEqual(json.loads(wrong_project.read_text())["result_count"], 0)
            allowed = root / "allowed.json"
            KB.query_index(first, allowed, registry="method", query="fixture", statuses={"reviewed_with_limits"}, grants={"public", "project_restricted"}, project_ids={"project_alpha"})
            allowed_data = json.loads(allowed.read_text())
            self.assertEqual(allowed_data["result_count"], 1)
            self.assertFalse(allowed_data["calculation_ready"])

            export_dir = root / "public-export"
            manifest = KB.export_index(
                first,
                export_dir,
                registry="structure",
                statuses={"reviewed"},
                grants={"public"},
                project_ids=set(),
            )
            self.assertEqual(manifest["record_count"], 1)
            exported_path = export_dir / manifest["records"][0]["path"]
            exported = KB.validate_record(KB.load_json(exported_path))
            canonical_path = KB.record_path(store, exported)
            self.assertEqual(exported_path.read_bytes(), canonical_path.read_bytes())
            self.assertFalse(manifest["content_objects_exported"])

    def test_link_access_cannot_expose_a_restricted_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            KB.ensure_store(store, create=True)
            method = self.finalize(self.method())
            source = self.finalize(self.source())
            unsafe_link = self.finalize(self.link(method, source, public=True))
            paths = []
            for record in (method, source, unsafe_link):
                path = root / f"{record['revision_id']}.json"
                path.write_bytes(KB.canonical_bytes(record))
                paths.append(path)
            self.commit_records(root, store, paths, "unsafe-link")
            with self.assertRaisesRegex(KB.KnowledgeError, "less restrictive"):
                KB.rebuild_index(store, root / "unsafe.sqlite3")
            self.assertFalse((root / "unsafe.sqlite3").exists())

    def test_snapshot_is_hash_bound_stable_and_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store, records = self.populated_store(root)
            _, parent_ref = self.parent_intake(root)
            request = self.snapshot_request(root, parent_ref, records)
            snapshot_path = root / "snapshot.json"
            snapshot = KB.build_snapshot(store, request, snapshot_path)
            self.assertFalse(snapshot["calculation_ready"])
            self.assertTrue(snapshot["no_submission_authorization"])
            original_bytes = snapshot_path.read_bytes()
            verification = KB.verify_snapshot(store, snapshot_path)
            self.assertEqual(verification["status"], "verified_immutable_snapshot")

            unrelated = self.method(
                logical_id="method_unrelated_draft",
                review_status="draft",
                access_class="public",
                project_ids=[],
            )
            unrelated["data"]["basis_by_element"] = {}
            unrelated["data"]["scope"]["elements"] = []
            unrelated_path = self.write_record(root, unrelated)
            self.commit_records(root, store, [unrelated_path], "unrelated")
            stale_index = root / "pre-update.sqlite3"
            KB.rebuild_index(store, stale_index)
            newer = self.method(
                logical_id="method_another_draft",
                review_status="draft",
                access_class="public",
                project_ids=[],
            )
            newer["data"]["basis_by_element"] = {}
            newer["data"]["scope"]["elements"] = []
            newer_path = self.write_record(root, newer)
            self.commit_records(root, store, [newer_path], "newer")
            with self.assertRaisesRegex(KB.KnowledgeError, "stale derived index"):
                KB.verify_index(store, stale_index)
            after = KB.verify_snapshot(store, snapshot_path)
            self.assertEqual(after["snapshot_payload_sha256"], snapshot["payload_sha256"])
            self.assertEqual(snapshot_path.read_bytes(), original_bytes)

    def test_fresh_reviewed_w1_intake_binds_an_offline_w2_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            intake_path = root / "reaction-intake.json"
            built = subprocess.run(
                [
                    sys.executable,
                    str(W1_SCRIPT),
                    "build-intake",
                    str(W1_FIXTURES / "intake_request.json"),
                    "--scheme",
                    str(W1_FIXTURES / "normalized_scheme.json"),
                    "--output",
                    str(intake_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(built.returncode, 0)
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            self.assertEqual(intake["schema"], "gaussian-reaction-intake/1")
            self.assertEqual(intake["gate_status"], "reviewed")
            self.assertFalse(intake["calculation_ready"])
            self.assertTrue(intake["no_submission_authorization"])

            store, records = self.populated_store(root)
            parent_ref = {
                "path": intake_path.name,
                "sha256": KB.sha256_file(intake_path),
                "payload_sha256": intake["payload_sha256"],
            }
            request_path = self.snapshot_request(root, parent_ref, records)
            snapshot_path = root / "w1-w2-snapshot.json"
            snapshot = KB.build_snapshot(store, request_path, snapshot_path)
            verified = KB.verify_snapshot(store, snapshot_path)

            self.assertEqual(snapshot["data"]["parent_reaction_intake"], parent_ref)
            self.assertEqual(verified["status"], "verified_immutable_snapshot")
            self.assertEqual(verified["selected_record_count"], len(records))
            self.assertFalse(snapshot["calculation_ready"])
            self.assertTrue(snapshot["no_submission_authorization"])

    def test_snapshot_refuses_draft_and_parent_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            KB.ensure_store(store, create=True)
            draft = self.method(logical_id="method_draft_only", review_status="draft", access_class="public", project_ids=[])
            draft["data"]["basis_by_element"] = {}
            draft["data"]["scope"]["elements"] = []
            draft_record = self.finalize(draft)
            draft_path = root / "draft.json"
            draft_path.write_bytes(KB.canonical_bytes(draft_record))
            self.commit_records(root, store, [draft_path], "draft")
            parent_path, parent_ref = self.parent_intake(root)
            request = self.snapshot_request(root, parent_ref, [draft_record])
            with self.assertRaisesRegex(KB.KnowledgeError, "unreviewed revision"):
                KB.build_snapshot(store, request, root / "draft-snapshot.json")
            parent_path.write_text(parent_path.read_text() + " ", encoding="utf-8")
            with self.assertRaisesRegex(KB.KnowledgeError, "file SHA-256 mismatch"):
                KB.build_snapshot(store, request, root / "drift-snapshot.json")

    def test_duplicate_keys_nonfinite_json_and_missing_objects_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
            failed = self.run_cli("validate", str(duplicate), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("duplicate JSON key", failed.stderr)
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"value":NaN}', encoding="utf-8")
            failed = self.run_cli("validate", str(nonfinite), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("non-standard JSON numeric constant", failed.stderr)

            store = root / "store"
            KB.ensure_store(store, create=True)
            object_ref = {
                "sha256": KB.sha256_file(OBJECT_FIXTURE),
                "size_bytes": OBJECT_FIXTURE.stat().st_size,
                "media_type": "chemical/x-daylight-smiles",
                "original_name": OBJECT_FIXTURE.name,
            }
            record_path = self.write_record(root, self.structure(object_ref))
            self.commit_records(root, store, [record_path], "missing-object")
            with self.assertRaisesRegex(KB.KnowledgeError, "referenced object is missing"):
                KB.rebuild_index(store, root / "missing-object.sqlite3")

            restricted_store = root / "restricted-object-store"
            KB.ensure_store(restricted_store, create=True)
            object_args = {
                "media_type": "chemical/x-daylight-smiles",
                "license_name": "internal fixture",
                "access_class": "group_internal",
                "storage_status": "lawful_local_object",
                "project_ids": [],
            }
            object_dry = root / "restricted-object-dry.json"
            KB.import_object(restricted_store, OBJECT_FIXTURE, object_dry, **object_args, commit=False)
            object_commit = KB.import_object(
                restricted_store,
                OBJECT_FIXTURE,
                root / "restricted-object-commit.json",
                **object_args,
                commit=True,
                approved_dry_run=object_dry,
            )
            public_record_path = self.write_record(root, self.structure(object_commit["object"], logical_id="structure_public_leak"))
            self.commit_records(root, restricted_store, [public_record_path], "public-leak-record")
            with self.assertRaisesRegex(KB.KnowledgeError, "less restrictive than a referenced object"):
                KB.rebuild_index(restricted_store, root / "public-leak.sqlite3")


if __name__ == "__main__":
    unittest.main()
