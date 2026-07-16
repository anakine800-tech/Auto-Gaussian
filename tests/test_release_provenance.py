#!/usr/bin/env python3
"""Offline tests for Auto-G16 release identity and citation evidence."""

from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "release_provenance.py"
SPEC = importlib.util.spec_from_file_location("auto_g16_release_provenance", MODULE_PATH)
assert SPEC and SPEC.loader
PROVENANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROVENANCE)


class ReleaseProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest_path = ROOT / "release-manifests" / "v2.3.0.json"
        self.manifest = PROVENANCE.load_json(self.manifest_path)

    def test_checked_v230_manifest_matches_tag_and_citation(self) -> None:
        git_available = (ROOT / ".git").exists()
        PROVENANCE.validate_manifest(ROOT, self.manifest, check_git=git_available)
        if git_available:
            rebuilt = PROVENANCE.make_manifest(
                ROOT,
                tag="v2.3.0",
                published_at="2026-07-16T04:58:20Z",
                release_url=(
                    "https://github.com/anakine800-tech/Auto-Gaussian/"
                    "releases/tag/v2.3.0"
                ),
                citation_path="release-manifests/citations/v2.3.0.cff",
                artifacts=[],
                version_doi=None,
                concept_doi=None,
                swhid=(
                    "swh:1:rev:3125b46eec8176812d5e927ef2dbddd86d2c936b"
                ),
            )
            self.assertEqual(rebuilt, self.manifest)
        self.assertFalse(self.manifest["source"]["signature"]["present"])
        self.assertFalse(self.manifest["source"]["signature"]["required"])

    def test_every_release_after_v230_requires_a_declared_signature(self) -> None:
        future = copy.deepcopy(self.manifest)
        future["version"] = "2.4.0"
        future["tag"] = "v2.4.0"
        future["release_url"] = (
            "https://github.com/anakine800-tech/Auto-Gaussian/"
            "releases/tag/v2.4.0"
        )
        future["manifest_status"] = "release_native"
        with self.assertRaisesRegex(PROVENANCE.ProvenanceError, "classification drift"):
            PROVENANCE.validate_manifest(ROOT, future, check_git=False)
        future["source"]["signature"]["required"] = True
        with self.assertRaisesRegex(PROVENANCE.ProvenanceError, "missing its required"):
            PROVENANCE.validate_manifest(ROOT, future, check_git=False)
        future["source"]["signature"] = {
            "format": "ssh",
            "present": True,
            "required": True,
        }
        future["identifiers"]["software_heritage_swhid"] = None
        PROVENANCE.validate_manifest(ROOT, future, check_git=False)

    def test_citation_and_artifact_bindings_reject_byte_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            citation_snapshot = (
                temp_root / "release-manifests" / "citations" / "v2.3.0.cff"
            )
            citation_snapshot.parent.mkdir(parents=True, exist_ok=True)
            citation_snapshot.write_bytes(
                (ROOT / "release-manifests" / "citations" / "v2.3.0.cff").read_bytes()
            )
            manifest = copy.deepcopy(self.manifest)
            PROVENANCE.validate_manifest(temp_root, manifest, check_git=False)
            citation_snapshot.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(PROVENANCE.ProvenanceError, "byte size drift"):
                PROVENANCE.validate_manifest(temp_root, manifest, check_git=False)

    def test_identifier_backfill_is_fill_only_and_updates_readme_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            citation_snapshot = (
                temp_root / "release-manifests" / "citations" / "v2.3.0.cff"
            )
            citation_snapshot.parent.mkdir(parents=True, exist_ok=True)
            citation_snapshot.write_bytes(
                (ROOT / "release-manifests" / "citations" / "v2.3.0.cff").read_bytes()
            )
            manifest_path = temp_root / "v2.3.0.json"
            initial = copy.deepcopy(self.manifest)
            initial["identifiers"] = {
                "concept_doi": None,
                "software_heritage_swhid": None,
                "version_doi": None,
            }
            manifest_path.write_text(
                PROVENANCE.canonical_json(initial), encoding="utf-8"
            )
            readme = temp_root / "README.md"
            readme.write_text(
                "version <!-- release-provenance:version-doi:start -->pending"
                "<!-- release-provenance:version-doi:end -->\n"
                "concept <!-- release-provenance:concept-doi:start -->pending"
                "<!-- release-provenance:concept-doi:end -->\n"
                "archive <!-- release-provenance:swhid:start -->pending"
                "<!-- release-provenance:swhid:end -->\n",
                encoding="utf-8",
            )
            swhid = (
                "swh:1:rev:3125b46eec8176812d5e927ef2dbddd86d2c936b"
            )
            PROVENANCE.update_identifiers(
                temp_root,
                manifest_path,
                version_doi="10.5281/zenodo.12345678",
                concept_doi="10.5281/zenodo.12345670",
                swhid=swhid,
                readme_path=readme,
            )
            finalized = PROVENANCE.load_json(manifest_path)
            self.assertEqual(
                finalized["identifiers"],
                {
                    "concept_doi": "10.5281/zenodo.12345670",
                    "software_heritage_swhid": swhid,
                    "version_doi": "10.5281/zenodo.12345678",
                },
            )
            readme_text = readme.read_text(encoding="utf-8")
            self.assertIn("`10.5281/zenodo.12345678`", readme_text)
            self.assertIn(f"`{swhid}`", readme_text)
            with self.assertRaisesRegex(PROVENANCE.ProvenanceError, "refusing to replace"):
                PROVENANCE.update_identifiers(
                    temp_root,
                    manifest_path,
                    version_doi="10.5281/zenodo.99999999",
                    concept_doi="10.5281/zenodo.12345670",
                    swhid=swhid,
                    readme_path=None,
                )

    def test_strict_json_and_closed_manifest_reject_ambiguous_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
            with self.assertRaisesRegex(PROVENANCE.ProvenanceError, "duplicate JSON key"):
                PROVENANCE.load_json(path)
        unknown = copy.deepcopy(self.manifest)
        unknown["unexpected"] = True
        with self.assertRaisesRegex(PROVENANCE.ProvenanceError, "unknown"):
            PROVENANCE.validate_manifest(ROOT, unknown, check_git=False)
        wrong_revision = copy.deepcopy(self.manifest)
        wrong_revision["identifiers"]["software_heritage_swhid"] = (
            "swh:1:rev:" + "f" * 40
        )
        with self.assertRaisesRegex(PROVENANCE.ProvenanceError, "Git commit SHA disagree"):
            PROVENANCE.validate_manifest(ROOT, wrong_revision, check_git=False)

    def test_research_output_template_requires_exact_reproducibility_fields(self) -> None:
        template = (
            ROOT / "docs" / "research-output-citation-template.md"
        ).read_text(encoding="utf-8")
        for required in (
            "Auto-G16 version DOI",
            "Auto-G16 Git commit",
            "Gaussian input SHA-256 values",
            "Workflow-manifest SHA-256 values",
            "Evidence access classification",
        ):
            self.assertIn(required, template)


if __name__ == "__main__":
    unittest.main()
