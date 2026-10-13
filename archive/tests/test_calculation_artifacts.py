#!/usr/bin/env python3
"""Offline integration and refusal tests for calculation-artifact adapters."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "calculation_artifacts.py"
PROTOCOL_PATH = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "protocol_selection.py"
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow" / "calculation_artifacts"
ASYM_FIXTURES = ROOT / "tests" / "fixtures" / "asymmetric_catalysis"
SCHEMAS = ROOT / "contracts" / "reaction-workflow"

SPEC = importlib.util.spec_from_file_location("calculation_artifacts_test", MODULE_PATH)
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refinalize(value: dict) -> dict:
    """Recompute an adapter payload hash without invoking schema validation."""
    value = copy.deepcopy(value)
    value.pop("payload_sha256", None)
    return ADAPTER.rw.finalize_artifact(value)


class CalculationArtifactTests(unittest.TestCase):
    maxDiff = None

    def assert_adapter_document_valid(self, document: dict) -> None:
        ADAPTER._validate_adapter_document(document)
        ADAPTER._validate_payload(document)

    def make_study_candidate(self, root: Path) -> tuple[Path, Path, Path, dict, dict]:
        xyz = root / "main_group_ts.xyz"
        shutil.copy2(FIXTURES / "main_group_ts.xyz", xyz)
        study = json.loads((ASYM_FIXTURES / "boron_study.json").read_text(encoding="utf-8"))
        extra_dimensions = [
            {
                "dimension_id": "ion_pair_placement",
                "name": "Ion-pair placement",
                "applicable": True,
                "expected_levels": ["not_present"],
                "review_rule": "Synthetic fixture has no ion pair.",
            },
            {
                "dimension_id": "electronic_state_hypothesis",
                "name": "Electronic state",
                "applicable": True,
                "expected_levels": ["closed_shell_singlet"],
                "review_rule": "Synthetic fixture is reviewed as a closed-shell singlet.",
            },
        ]
        study["coverage_dimensions"].extend(extra_dimensions)
        study["comparison_groups"][0]["coverage_dimension_ids"].extend(
            ["ion_pair_placement", "electronic_state_hypothesis"]
        )
        study_path = root / "study.json"
        dump(study_path, study)

        candidate = json.loads((ASYM_FIXTURES / "boron_candidate_r.json").read_text(encoding="utf-8"))
        candidate["study_sha256"] = digest(study_path)
        candidate["geometry"] = {
            "format": "xyz",
            "artifact": {"path": str(xyz), "sha256": digest(xyz)},
            "construction_method": "Sanitized deterministic Cartesian fixture.",
            "stereochemistry_reviewed": True,
            "clash_reviewed": True,
        }
        candidate["candidate_dimensions"].update(
            {
                "ion_pair_placement": "not_present",
                "electronic_state_hypothesis": "closed_shell_singlet",
            }
        )
        candidate["coverage_tags"] = copy.deepcopy(candidate["candidate_dimensions"])
        candidate["resource_tier_proposal"] = "simple"
        candidate_path = root / "candidate.json"
        dump(candidate_path, candidate)
        return study_path, candidate_path, xyz, study, candidate

    def profile(self, tier: str) -> dict:
        return {
            "profile_id": f"fixture_{tier}_ts_freq_profile",
            "stages": ["transition_state_optimization", "harmonic_frequency"],
            "functional_or_method": f"reviewed_{tier}_method",
            "basis_stack": [
                {
                    "elements": ["B", "C", "H", "O"],
                    "orbital_basis": f"reviewed_{tier}_basis",
                    "ecp": None,
                    "ecp_core_electrons": None,
                    "aux_basis": None,
                }
            ],
            "dispersion": {"mode": "reviewed", "detail": f"{tier} fixture"},
            "solvation": {
                "mode": "continuum",
                "model": "reviewed_fixture_model",
                "solvent_identity": "reviewed_fixture_solvent",
                "explicit_species": [],
            },
            "grid": f"reviewed_{tier}_grid",
            "scf": {
                "reference": "restricted_closed_shell",
                "convergence": f"reviewed_{tier}_convergence",
                "max_cycles": 128,
                "stability_check": "not included",
                "broken_symmetry_policy": "not_applicable",
            },
            "relativistic_treatment": "not_required_for_fixture_elements",
            "software_compatibility": "reviewed_for_installed_g16",
        }

    def option(self, tier: str) -> dict:
        ranks = {"loose": 1, "standard": 2, "strict": 3}
        names = {"loose": "\u5bbd\u677e", "standard": "\u6807\u51c6", "strict": "\u4e25\u683c"}
        return {
            "option_id": f"fixture_{tier}_ts_freq",
            "tier": tier,
            "display_name": names[tier],
            "rigor_rank": ranks[tier],
            "option_status": "selectable",
            "purpose": f"Reviewed {tier} TS/Freq fixture protocol.",
            "applicability": {
                "task_types": ["transition_state_optimization", "harmonic_frequency"],
                "system_classes": ["main_group_closed_shell"],
                "prerequisites": ["reviewed candidate"],
                "exclusions": ["metal and open-shell systems"],
                "fit_assessment": "reviewed",
                "reason": f"Explicit {tier} fixture choice.",
            },
            "method_profiles": [self.profile(tier)],
            "task_plan": [
                {
                    "stage_type": "single_guess_ts_opt_freq",
                    "profile_id": f"fixture_{tier}_ts_freq_profile",
                    "required": True,
                    "acceptance_checks": ["stationary point", "complete frequencies", "manual mode review"],
                }
            ],
            "validation_plan": {"minimum_acceptance": ["manual mode review"], "claim_limit": f"{tier} fixture only"},
            "coverage_plan": {"structures": "one reviewed fixture", "sensitivity": tier},
            "resources": {
                "resource_tier": "simple",
                "mem_gb": 12,
                "cores": 8,
                "job_count": 1,
                "relative_cost_units": {"loose": 1, "standard": 2, "strict": 3}[tier],
                "assumptions": ["qualitative fixture estimate only"],
            },
            "expected_cost": {"band": tier, "drivers": ["fixture stage"], "confidence": "qualitative"},
            "limitations": ["Fixture protocol is not a research default."],
            "provenance": ["Explicit sanitized fixture values."],
            "unresolved": [],
        }

    def make_protocol(self, root: Path, xyz: Path) -> tuple[Path, Path, dict, dict]:
        request = {
            "schema": "gaussian-calculation-request/1",
            "request_id": "fixture_main_group_ts_freq",
            "goal": "Render one exact reviewed TS/Freq draft.",
            "claim_scope": "One closed-shell main-group single-guess TS/Freq candidate.",
            "task_types": ["transition_state_optimization", "harmonic_frequency"],
            "structure": {
                "sha256": digest(xyz),
                "formula": "C2H2BO",
                "atom_count": 6,
                "elements": ["B", "C", "H", "O"],
                "charge": 0,
                "multiplicity": 1,
            },
            "system_class": "main_group_closed_shell",
            "support_status": "supported",
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        request_path = root / "request.json"
        dump(request_path, request)
        profiles = {
            "schema": "gaussian-protocol-profile-source/1",
            "proposal_id": "fixture_main_group_three_tiers",
            "difficulty_assessment": {"class": "fixture", "drivers": ["TS/Freq"], "evidence": ["sanitized XYZ"], "review_status": "reviewed"},
            "common_constraints": {"comparison_scope": "No comparison energy.", "temperature_k": 298.15, "standard_state": "unselected"},
            "options": [self.option(tier) for tier in ("loose", "standard", "strict")],
            "comparison_notes": ["Protocol rigor and resource tier remain separate decisions."],
            "non_claims": ["Strict is not an accuracy guarantee.", "No option authorizes submission."],
        }
        profiles_path = root / "profiles.json"
        dump(profiles_path, profiles)
        options_path = root / "options.json"
        options = ADAPTER.protocol.build_options(request_path, profiles_path)
        ADAPTER.protocol.write_new_json(options_path, options)
        approval_path = root / "approval.json"
        dump(
            approval_path,
            {
                "decision": "selected",
                "tier": "standard",
                "explicit_confirmation": True,
                "decision_reason": "Fixture reviewer selected the exact standard option.",
            },
        )
        selection = ADAPTER.protocol.build_selection(options_path, "standard", approval_path)
        selection_path = root / "selection.json"
        ADAPTER.protocol.write_new_json(selection_path, selection)
        return options_path, selection_path, options, selection

    def make_input_chain(self, root: Path) -> dict[str, object]:
        study_path, candidate_path, xyz, study, candidate = self.make_study_candidate(root)
        options_path, selection_path, options, selection = self.make_protocol(root, xyz)
        review = {
            "schema": ADAPTER.INPUT_REVIEW_SCHEMA,
            "review_id": "fixture_exact_ts_draft",
            "workflow_kind": ADAPTER.V1_WORKFLOW,
            "candidate_id": candidate["candidate_id"],
            "protocol_id": candidate["protocol_id"],
            "sources": {
                "study": ADAPTER.artifact_ref(study_path, study),
                "candidate": ADAPTER.artifact_ref(candidate_path, candidate),
                "geometry": ADAPTER.artifact_ref(xyz, schema="chemical/x-xyz"),
                "protocol_options": ADAPTER.artifact_ref(options_path, options),
                "protocol_selection": ADAPTER.artifact_ref(selection_path, selection),
            },
            "identity": {
                "formula": candidate["atom_inventory"]["formula"],
                "element_counts": candidate["atom_inventory"]["element_counts"],
                "atom_count": candidate["atom_inventory"]["atom_count"],
                "atom_order": [
                    {"index": atom["index"], "element": atom["element"], "source_atom_id": atom["source_atom_id"]}
                    for atom in candidate["atom_map"]
                ],
                "charge": 0,
                "multiplicity": 1,
            },
            "link0": {"chk": "fixture_ts.chk", "mem": "12GB", "nprocshared": 8},
            "route": "#p b3lyp/6-31g(d) opt=(ts,calcfc,tight) freq int=ultrafine",
            "resources": {"resource_tier": "simple", "memory_gb": 12, "cores": 8, "expected_stage_count": 1},
            "title": "Sanitized exact closed-shell main-group TS/Freq draft",
            "trailing_sections": [],
            "expected_input_sha256": "0" * 64,
            "decision": {
                "status": "accepted_exact_draft",
                "reviewer": "fixture reviewer",
                "reviewed_on": "2026-07-16",
                "explicit_confirmation": True,
                "notes": ["Exact fixture route, resources, title, identity and atom order reviewed."],
            },
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        elements, coordinates = ADAPTER.asym.parse_xyz(xyz)
        review["expected_input_sha256"] = hashlib.sha256(ADAPTER._render_input(review, elements, coordinates)).hexdigest()
        ADAPTER._finalize(review)
        review_path = root / "input-review.json"
        dump(review_path, review)
        return {
            "study_path": study_path,
            "candidate_path": candidate_path,
            "xyz": xyz,
            "study": study,
            "candidate": candidate,
            "options_path": options_path,
            "selection_path": selection_path,
            "options": options,
            "selection": selection,
            "review_path": review_path,
            "review": review,
        }

    def build_handoff(self, root: Path, chain: dict[str, object]) -> tuple[Path, Path, bytes, dict]:
        input_path = root / "fixture_ts.gjf"
        manifest_path = root / "fixture_ts.handoff.json"
        input_bytes, handoff = ADAPTER.build_input_handoff(
            chain["study_path"], chain["candidate_path"], chain["options_path"],
            chain["selection_path"], chain["review_path"], input_path, manifest_path,
        )
        return input_path, manifest_path, input_bytes, handoff

    def mutate_review(self, chain: dict[str, object], mutator) -> None:
        review = copy.deepcopy(chain["review"])
        review.pop("payload_sha256")
        mutator(review)
        elements, coordinates = ADAPTER.asym.parse_xyz(chain["xyz"])
        review["expected_input_sha256"] = hashlib.sha256(ADAPTER._render_input(review, elements, coordinates)).hexdigest()
        ADAPTER._finalize(review)
        dump(chain["review_path"], review)
        chain["review"] = review

    def test_closed_draft_2020_12_schemas_are_fail_closed(self) -> None:
        names = {
            "candidate-target-import.schema.json", "input-draft-review.schema.json",
            "candidate-input-handoff.schema.json", "energy-review.schema.json",
            "reviewed-energy-record.schema.json", "energy-lineage.schema.json",
            "sanitized-job-observation.schema.json", "calculation-attempt-link.schema.json",
        }
        self.assertTrue(names <= {path.name for path in SCHEMAS.glob("*.schema.json")})
        for name in names:
            schema = ADAPTER.rw.load_json(SCHEMAS / name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            ADAPTER.asym_contract.validate_schema_document(schema)

    def test_every_emitted_adapter_document_validates_against_its_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            chain = artifacts["chain"]
            ledger_path, _ = self.make_ledger(root, chain)
            target_path = root / "target-import.json"
            target = ADAPTER.build_target_import(
                chain["study_path"], ledger_path, target_path, "fixture_target_import"
            )
            record_path = root / "energy-record.json"
            lineage_path = root / "energy-lineage.json"
            record, lineage = ADAPTER.build_energy_projection(
                chain["candidate_path"], artifacts["parsed_path"], artifacts["energy_review_path"],
                record_path, lineage_path,
            )
            attempt = self.build_attempt(root, artifacts)
            documents = [
                chain["review"],
                target,
                artifacts["handoff"],
                ADAPTER.rw.load_json(artifacts["energy_review_path"]),
                record,
                lineage,
                artifacts["job"],
                attempt,
            ]
            self.assertEqual(
                {document["schema"] for document in documents},
                set(ADAPTER.ADAPTER_SCHEMA_PATHS),
            )
            for document in documents:
                with self.subTest(schema=document["schema"]):
                    self.assert_adapter_document_valid(document)

    def test_unknown_top_level_and_nested_fields_are_rejected_after_payload_rehash(self) -> None:
        mutations = (
            ("top-level", lambda review: review.__setitem__("unknown_adapter_field", True)),
            ("nested", lambda review: review["identity"].__setitem__("unknown_identity_field", True)),
            ("artifact-ref", lambda review: review["sources"]["protocol_selection"].__setitem__("unknown_ref_field", True)),
        )
        for label, mutation in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                chain = self.make_input_chain(root)
                review = copy.deepcopy(chain["review"])
                mutation(review)
                dump(chain["review_path"], refinalize(review))
                with self.assertRaisesRegex(ADAPTER.AdapterError, "schema rejected|unknown"):
                    ADAPTER.validate_artifact(chain["review_path"])

    def test_input_handoff_is_deterministic_delegated_and_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            with mock.patch.object(ADAPTER.rtwin, "parse_gaussian", wraps=ADAPTER.rtwin.parse_gaussian) as delegated:
                input_path, manifest_path, first_bytes, handoff = self.build_handoff(root, chain)
            self.assertEqual(delegated.call_count, 1)
            self.assertEqual(input_path.read_bytes(), first_bytes)
            self.assertEqual(manifest_path.name, "fixture_ts.handoff.json")
            self.assertFalse(handoff["calculation_ready"])
            self.assertTrue(handoff["no_submission_authorization"])
            self.assertEqual(handoff["gate_separation"]["live_approval"], "absent")
            first_manifest = manifest_path.read_bytes()
            input_path.unlink()
            manifest_path.unlink()
            _, _, second_bytes, _ = self.build_handoff(root, chain)
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(first_manifest, manifest_path.read_bytes())

    def test_input_handoff_refuses_overwrite_and_specialist_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            self.build_handoff(root, chain)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "overwrite"):
                self.build_handoff(root, chain)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            with mock.patch.object(ADAPTER.rtwin, "parse_gaussian", side_effect=SystemExit(2)):
                with self.assertRaisesRegex(ADAPTER.AdapterError, "specialist validator"):
                    self.build_handoff(root, chain)
            self.assertFalse((root / "fixture_ts.gjf").exists())
            self.assertFalse((root / "fixture_ts.handoff.json").exists())

    def test_input_handoff_refuses_candidate_xyz_formula_atom_charge_and_spin_drift(self) -> None:
        mutations = (
            ("atom order", lambda candidate: candidate["atom_map"].__setitem__(0, {**candidate["atom_map"][0], "element": "C"})),
            ("formula", lambda candidate: candidate["atom_inventory"].__setitem__("formula", "C2H3BO")),
            ("element counts", lambda candidate: candidate["atom_inventory"]["element_counts"].__setitem__("H", 3)),
            ("charge", lambda candidate: candidate["electronic_state"].__setitem__("charge", 1)),
            ("closed-shell singlets", lambda candidate: (candidate["electronic_state"].__setitem__("multiplicity", 2), candidate["chemical_state"].__setitem__("multiplicity", 2))),
        )
        for label, mutation in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                chain = self.make_input_chain(root)
                candidate = copy.deepcopy(chain["candidate"])
                mutation(candidate)
                candidate["study_sha256"] = digest(chain["study_path"])
                dump(chain["candidate_path"], candidate)
                with self.assertRaisesRegex(ADAPTER.AdapterError, label):
                    self.build_handoff(root, chain)

    def test_input_handoff_refuses_xyz_byte_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            original = chain["xyz"].read_text(encoding="utf-8")
            chain["xyz"].write_text(original.replace("1.35000000", "1.35000001"), encoding="utf-8")
            with self.assertRaisesRegex(ADAPTER.AdapterError, "geometry SHA-256 drift"):
                self.build_handoff(root, chain)
            self.assertFalse((root / "fixture_ts.gjf").exists())
            self.assertFalse((root / "fixture_ts.handoff.json").exists())

    def test_selection_options_and_review_refs_reject_path_size_payload_and_hash_drift(self) -> None:
        for source_name, field in (
            (source_name, field)
            for source_name in ("protocol_options", "protocol_selection", "input_review")
            for field in ("path", "size_bytes", "payload_sha256", "sha256")
        ):
            with self.subTest(source=source_name, field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                chain = self.make_input_chain(root)
                _, manifest_path, _, handoff = self.build_handoff(root, chain)
                if source_name == "input_review":
                    reference = copy.deepcopy(handoff["sources"][source_name])
                    path = chain["review_path"]
                    data = chain["review"]
                    owner = manifest_path
                else:
                    reference = copy.deepcopy(chain["review"]["sources"][source_name])
                    path = chain["options_path"] if source_name == "protocol_options" else chain["selection_path"]
                    data = chain["options"] if source_name == "protocol_options" else chain["selection"]
                    owner = chain["review_path"]
                if field == "path":
                    reference[field] = str(root / "missing-artifact.json")
                elif field == "size_bytes":
                    reference[field] += 1
                else:
                    reference[field] = "f" * 64 if reference[field] != "f" * 64 else "e" * 64
                with self.assertRaisesRegex(ADAPTER.AdapterError, "path differs|artifact reference drift"):
                    ADAPTER._validate_ref(reference, path, data, source_name, owner=owner)

    def test_input_handoff_refuses_review_payload_forgery_and_review_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            review = copy.deepcopy(chain["review"])
            review["title"] += " forged without payload rehash"
            dump(chain["review_path"], review)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "payload"):
                self.build_handoff(root, chain)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            real_review = root / "real-input-review.json"
            chain["review_path"].replace(real_review)
            try:
                chain["review_path"].symlink_to(real_review)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ADAPTER.AdapterError, "symlink"):
                self.build_handoff(root, chain)

    def test_input_handoff_refuses_options_selection_review_resource_route_and_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            options = copy.deepcopy(chain["options"])
            options["options"][1]["purpose"] += " drift"
            dump(chain["options_path"], options)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "hash"):
                self.build_handoff(root, chain)
        for label, mutation, pattern in (
            ("resource", lambda review: review["resources"].__setitem__("cores", 7), "resource"),
            ("route", lambda review: review.__setitem__("route", "#p b3lyp/6-31g(d) opt=(ts,calcfc) freq int=fine"), "SHA-256|route"),
            ("input hash", lambda review: review.__setitem__("expected_input_sha256", "f" * 64), "SHA-256"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                chain = self.make_input_chain(root)
                review = copy.deepcopy(chain["review"])
                review.pop("payload_sha256")
                mutation(review)
                if label not in {"input hash", "route"}:
                    elements, coordinates = ADAPTER.asym.parse_xyz(chain["xyz"])
                    review["expected_input_sha256"] = hashlib.sha256(ADAPTER._render_input(review, elements, coordinates)).hexdigest()
                ADAPTER._finalize(review)
                dump(chain["review_path"], review)
                with self.assertRaisesRegex(ADAPTER.AdapterError, pattern):
                    self.build_handoff(root, chain)

    def test_input_handoff_refuses_metal_qst_irc_allcheck_link1_and_trailing_sections(self) -> None:
        cases = (
            "#p b3lyp/6-31g(d) opt=(qst2,ts) freq",
            "#p b3lyp/6-31g(d) irc=(forward) freq",
            "#p b3lyp/6-31g(d) opt=ts freq geom=allcheck",
            "#p b3lyp/6-31g(d) opt=ts freq geom=(allcheck)",
            "#p b3lyp/6-31g(d) opt=ts freq guess=(read)",
            "#p oniom(test:test) opt=ts freq",
            "#p b3lyp/genecp opt=ts freq",
            "#p b3lyp/6-31g(d) opt=ts freq --Link1--",
        )
        for route in cases:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                chain = self.make_input_chain(root)
                self.mutate_review(chain, lambda review: review.__setitem__("route", route))
                with self.assertRaises(ADAPTER.AdapterError):
                    self.build_handoff(root, chain)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "trailing"):
                self.mutate_review(chain, lambda review: review.__setitem__("trailing_sections", ["unreviewed basis block"]))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            candidate = copy.deepcopy(chain["candidate"])
            candidate["support_status"] = "unsupported_transition_metal"
            candidate["review_status"] = "rejected"
            candidate["review"]["decision"] = "rejected"
            dump(chain["candidate_path"], candidate)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "unsupported|promoted"):
                self.build_handoff(root, chain)

    def make_ledger(self, root: Path, chain: dict[str, object]) -> tuple[Path, list[Path]]:
        base = chain["candidate"]
        candidate_paths: list[Path] = [chain["candidate_path"]]
        variants = []
        for candidate_id, support, review_status in (
            ("boron_ts_rejected", "supported_main_group_closed_shell", "rejected"),
            ("boron_ts_unsupported", "unsupported_electronic_structure", "rejected"),
        ):
            candidate = copy.deepcopy(base)
            candidate["candidate_id"] = candidate_id
            candidate["support_status"] = support
            candidate["review_status"] = review_status
            candidate["review"]["decision"] = review_status
            path = root / f"{candidate_id}.json"
            dump(path, candidate)
            candidate_paths.append(path)
            variants.append((candidate, path))
        dimensions = base["candidate_dimensions"]
        common = {
            "channel_id": base["channel_id"],
            "catalyst_state_id": base["catalyst_state_id"],
            "dimensions": dimensions,
            "duplicate_of": None,
            "geometry_fingerprint": {"method": "sanitized_fixture", "sha256": "9" * 64},
            "diagnostics": [],
        }
        entries = []
        for index, (candidate, path) in enumerate([(base, chain["candidate_path"]), *variants], start=1):
            entries.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    **common,
                    "canonical_key": str(index) * 64,
                    "logical_equivalence_key": str(index) * 64,
                    "status": "materialized_unique",
                    "candidate_artifact": {"path": str(path), "sha256": digest(path)},
                }
            )
        entries.extend(
            [
                {
                    "candidate_id": "boron_ts_duplicate_logical", **common,
                    "canonical_key": "4" * 64, "logical_equivalence_key": "1" * 64,
                    "status": "duplicate_logical", "duplicate_of": base["candidate_id"],
                    "candidate_artifact": None, "geometry_fingerprint": None,
                    "diagnostics": ["logical duplicate retained"],
                },
                {
                    "candidate_id": "boron_ts_duplicate_geometry", **common,
                    "canonical_key": "5" * 64, "logical_equivalence_key": "5" * 64,
                    "status": "duplicate_geometry", "duplicate_of": base["candidate_id"],
                    "candidate_artifact": None,
                    "diagnostics": ["geometry duplicate retained"],
                },
                {
                    "candidate_id": "boron_ts_proposed", **common,
                    "canonical_key": "6" * 64, "logical_equivalence_key": "6" * 64,
                    "status": "unmaterialized", "candidate_artifact": None, "geometry_fingerprint": None,
                    "diagnostics": ["proposed candidate retained"],
                },
            ]
        )
        ledger = {
            "schema": "gaussian-asymmetric-candidate-ledger/1",
            "study_id": base["study_id"],
            "study_sha256": digest(chain["study_path"]),
            "comparison_group_id": base["comparison_group_id"],
            "mechanism_id": base["mechanism_id"],
            "protocol_id": base["protocol_id"],
            "calculation_ready": False,
            "no_submission_authorization": True,
            "candidate_space_spec": {"path": "fixture://candidate-space", "sha256": "a" * 64},
            "geometry_dedup_tolerance_angstrom": 0.01,
            "dimension_ids": list(dimensions),
            "entries": entries,
            "excluded_combinations": [{"reason": "reviewed exclusion retained"}],
            "counts": {
                "enumerated": 7, "retained": 5, "logical_duplicates": 1, "excluded": 1,
                "materialized_unique": 3, "geometry_duplicates": 1,
            },
        }
        ledger_path = root / "candidate-ledger.json"
        dump(ledger_path, ledger)
        return ledger_path, candidate_paths

    def test_target_import_retains_all_dispositions_and_stable_external_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            ledger_path, _ = self.make_ledger(root, chain)
            output = root / "target-import.json"
            result = ADAPTER.build_target_import(chain["study_path"], ledger_path, output, "fixture_target_import")
            self.assertEqual(result["counts"]["targets"], 6)
            self.assertEqual(result["counts"]["eligible_for_later_input_review"], 1)
            self.assertEqual(len(result["excluded_combinations"]), 1)
            by_id = {target["candidate_id"]: target for target in result["targets"]}
            self.assertTrue(by_id[chain["candidate"]["candidate_id"]]["readiness_facts"]["eligible_for_later_input_review"])
            self.assertFalse(by_id["boron_ts_rejected"]["readiness_facts"]["eligible_for_later_input_review"])
            self.assertIn("candidate_support:unsupported_electronic_structure", by_id["boron_ts_unsupported"]["readiness_facts"]["blockers"])
            self.assertEqual(by_id["boron_ts_duplicate_logical"]["dependency_external_keys"], [by_id[chain["candidate"]["candidate_id"]]["external_target_key"]])
            self.assertNotIn("node_id", output.read_text(encoding="utf-8"))
            first = output.read_bytes()
            output.unlink()
            ADAPTER.build_target_import(chain["study_path"], ledger_path, output, "fixture_target_import")
            self.assertEqual(first, output.read_bytes())

    def test_target_import_rejects_duplicate_ledger_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            ledger_path, _ = self.make_ledger(root, chain)
            ledger = ADAPTER.rw.load_json(ledger_path)
            ledger["entries"][-1]["candidate_id"] = ledger["entries"][0]["candidate_id"]
            dump(ledger_path, ledger)
            output = root / "target-import.json"
            with self.assertRaisesRegex(ADAPTER.AdapterError, "duplicate (?:IDs|candidate_id)"):
                ADAPTER.build_target_import(
                    chain["study_path"], ledger_path, output, "fixture_target_import"
                )
            self.assertFalse(output.exists())

    def test_supported_but_triplet_target_is_retained_and_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            candidate = copy.deepcopy(chain["candidate"])
            candidate["chemical_state"]["multiplicity"] = 3
            candidate["electronic_state"]["multiplicity"] = 3
            candidate["electronic_state"]["spin_state_notes"] = "Synthetic reviewed triplet refusal fixture."
            dump(chain["candidate_path"], candidate)
            chain["candidate"] = candidate
            ledger_path, _ = self.make_ledger(root, chain)
            result = ADAPTER.build_target_import(
                chain["study_path"], ledger_path, root / "target-import.json", "fixture_target_import"
            )
            target = next(item for item in result["targets"] if item["candidate_id"] == candidate["candidate_id"])
            self.assertTrue(target["readiness_facts"]["supported_main_group_closed_shell"])
            self.assertFalse(target["readiness_facts"]["closed_shell_singlet"])
            self.assertFalse(target["readiness_facts"]["eligible_for_later_input_review"])
            self.assertIn("candidate_not_closed_shell_singlet", target["readiness_facts"]["blockers"])

    def make_energy_review(self, root: Path, candidate_path: Path, parsed_path: Path, *, accept: bool = True, with_decision: bool = True) -> tuple[Path, Path | None, Path | None]:
        mode_path = decision_path = None
        mode_ref = decision_ref = None
        parsed = ADAPTER.rw.load_json(parsed_path)
        if with_decision:
            imaginary_frequency = parsed["imaginary_modes"][0]["frequency_cm-1"]
            mode = {
                "schema": "gaussian-ts-mode-review/1",
                "ts_result_sha256": digest(parsed_path),
                "imaginary_frequency_cm-1": imaginary_frequency,
                "amplitude": 0.1,
                "distance_projections": [],
                "displacements": parsed["imaginary_modes"][0]["displacements"],
                "visualization_artifacts": ["mode_plus.xyz", "mode_minus.xyz"],
                "scientific_decision": "required",
            }
            mode_path = root / "mode-review.json"
            dump(mode_path, mode)
            decision = {
                "schema": "gaussian-ts-mode-decision/1",
                "ts_result_sha256": digest(parsed_path),
                "mode_review_sha256": digest(mode_path),
                "imaginary_frequency_cm-1": imaginary_frequency,
                "decision": "accepted",
                "confirmed": True,
            }
            decision_path = root / "mode-decision.json"
            dump(decision_path, decision)
            mode_ref = ADAPTER.artifact_ref(mode_path, mode)
            decision_ref = ADAPTER.artifact_ref(decision_path, decision)
        candidate = ADAPTER.rw.load_json(candidate_path)
        review = {
            "schema": ADAPTER.ENERGY_REVIEW_SCHEMA,
            "review_id": "fixture_electronic_energy",
            "candidate_id": candidate["candidate_id"],
            "sources": {
                "candidate": ADAPTER.artifact_ref(candidate_path, candidate),
                "parsed_result": ADAPTER.artifact_ref(parsed_path, parsed),
                "mode_review": mode_ref,
                "scientific_decision": decision_ref,
            },
            "decision": "accept_electronic_only" if accept else "blocked_insufficient_evidence",
            "allowed_projection_fields": ["final_energy_hartree"] if accept else [],
            "comparison_policy": {
                "temperature_k": None, "standard_state": None, "low_frequency_policy": None,
                "common_reference": None, "comparison_authorized": False,
            },
            "reviewer": "fixture reviewer",
            "reviewed_on": "2026-07-16",
            "notes": ["Project only the specialist final electronic energy; block all comparison use."],
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        ADAPTER._finalize(review)
        review_path = root / "energy-review.json"
        dump(review_path, review)
        return review_path, mode_path, decision_path

    def make_attempt_artifacts(self, root: Path) -> dict[str, object]:
        chain = self.make_input_chain(root)
        input_path, manifest_path, _, handoff = self.build_handoff(root, chain)
        parsed = json.loads((FIXTURES / "parsed_ts_result.json").read_text(encoding="utf-8"))
        parsed_path = root / "parsed-result.json"
        dump(parsed_path, parsed)
        energy_review_path, mode_path, decision_path = self.make_energy_review(
            root, chain["candidate_path"], parsed_path
        )
        self.assertIsNotNone(mode_path)
        self.assertIsNotNone(decision_path)
        source_job_sha = "b" * 64
        job = {
            "schema": ADAPTER.SANITIZED_JOB_SCHEMA,
            "observation_id": "fixture_job_observation",
            "source_job_sha256": source_job_sha,
            "input_sha256": digest(input_path),
            "status": "completed",
            "last_inspection_state": "completed",
            "redacted_fields": ["job_id", "remote_workdir"],
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        ADAPTER._finalize(job)
        job_path = root / "sanitized-job.json"
        dump(job_path, job)
        intake = {
            "schema": "gaussian-terminal-intake/1",
            "template_id": "fixture_terminal_template",
            "template_sha256": "c" * 64,
            "template_payload_sha256": "d" * 64,
            "task_kind": "ts_freq",
            "project": "fixture_ts",
            "runtime_job_id": "redacted-at-link-boundary",
            "artifacts": {
                "input_sha256": digest(input_path),
                "job_sha256": source_job_sha,
                "log_sha256": parsed["log_sha256"],
                "log_size_bytes": 4096,
            },
            "terminal_evidence": {
                "status": "passed",
                "job_state": "completed",
                "results_fetched": True,
                "process_alive": False,
                "submission_transport_hashes_verified": True,
                "normal_termination_count": 1,
                "error_termination_count": 0,
            },
            "automatic_action_authorized": False,
            "acceptance_status": "manual_review_required",
            "outcome": "ready_for_manual_mode_review",
            "scientific_evidence": {
                "optimization_completed": True,
                "stationary_point_found": True,
                "atom_count": 6,
                "expected_atom_count": 6,
                "frequency_count": 3,
                "expected_frequency_count": 3,
                "raw_imaginary_frequency_count": 1,
                "imaginary_frequencies_cm-1": [-250.0],
                "first_order_saddle_candidate": True,
                "mode_review_status": "pending",
            },
            "path_validated": False,
            "next_required_artifacts": [
                "gaussian-ts-freq-result/1",
                "gaussian-ts-mode-review/1",
                "gaussian-ts-mode-decision/1",
            ],
        }
        intake_path = root / "terminal-intake.json"
        dump(intake_path, intake)
        return {
            "chain": chain,
            "input_path": input_path,
            "manifest_path": manifest_path,
            "handoff": handoff,
            "parsed_path": parsed_path,
            "parsed": parsed,
            "energy_review_path": energy_review_path,
            "mode_path": mode_path,
            "decision_path": decision_path,
            "job_path": job_path,
            "job": job,
            "intake_path": intake_path,
            "intake": intake,
        }

    def build_attempt(self, root: Path, artifacts: dict[str, object], output_name: str = "attempt-link.json") -> dict:
        return ADAPTER.build_attempt_link(
            artifacts["handoff"]["external_target_key"],
            artifacts["manifest_path"],
            artifacts["job_path"],
            artifacts["intake_path"],
            artifacts["parsed_path"],
            artifacts["mode_path"],
            artifacts["decision_path"],
            root / output_name,
            "fixture_attempt_link",
        )

    def test_energy_projection_is_electronic_only_with_exact_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            parsed_path = root / "parsed-result.json"
            shutil.copy2(FIXTURES / "parsed_ts_result.json", parsed_path)
            review_path, _, _ = self.make_energy_review(root, chain["candidate_path"], parsed_path)
            record_path = root / "energy-record.json"
            lineage_path = root / "energy-lineage.json"
            record, lineage = ADAPTER.build_energy_projection(chain["candidate_path"], parsed_path, review_path, record_path, lineage_path)
            self.assertEqual(record["status"], "electronic_only")
            self.assertEqual(record["energy"]["electronic_energy"]["value"], -123.456789)
            self.assertIsNone(record["energy"]["thermal_gibbs_correction"])
            self.assertIsNone(record["energy"]["comparison_free_energy"])
            self.assertFalse(record["comparison_eligible"])
            self.assertTrue(lineage["specialist_classification_preserved"])
            self.assertEqual(lineage["sources"]["parsed_result"]["sha256"], digest(parsed_path))

    def test_energy_projection_blocks_missing_energy_review_and_raw_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            parsed = json.loads((FIXTURES / "parsed_ts_result.json").read_text(encoding="utf-8"))
            parsed["final_energy_hartree"] = None
            parsed_path = root / "parsed-result.json"
            dump(parsed_path, parsed)
            review_path, _, _ = self.make_energy_review(root, chain["candidate_path"], parsed_path)
            record, _ = ADAPTER.build_energy_projection(
                chain["candidate_path"], parsed_path, review_path,
                root / "blocked-energy.json", root / "blocked-lineage.json",
            )
            self.assertEqual(record["status"], "blocked")
            self.assertIn("finite_final_electronic_energy_absent", record["blockers"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            raw = root / "raw.log"
            raw.write_text("SCF Done: synthetic raw text\n", encoding="utf-8")
            review = root / "review.json"
            dump(review, {"schema": ADAPTER.ENERGY_REVIEW_SCHEMA})
            with self.assertRaisesRegex(ADAPTER.AdapterError, "TS/Freq JSON|JSON"):
                ADAPTER.build_energy_projection(chain["candidate_path"], raw, review, root / "record.json", root / "lineage.json")

    def test_energy_projection_without_scientific_review_is_explicitly_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            parsed_path = root / "parsed-result.json"
            shutil.copy2(FIXTURES / "parsed_ts_result.json", parsed_path)
            review_path, mode_path, decision_path = self.make_energy_review(
                root, chain["candidate_path"], parsed_path, with_decision=False
            )
            self.assertIsNone(mode_path)
            self.assertIsNone(decision_path)
            record, lineage = ADAPTER.build_energy_projection(
                chain["candidate_path"], parsed_path, review_path,
                root / "blocked-energy.json", root / "blocked-lineage.json",
            )
            self.assertEqual(record["status"], "blocked")
            self.assertIsNone(record["energy"]["electronic_energy"]["value"])
            self.assertIn("scientific_review_artifacts_absent", record["blockers"])
            self.assertEqual(lineage["projected_fields"], [])
            self.assertIsNone(lineage["sources"]["mode_review"])
            self.assertIsNone(lineage["sources"]["scientific_decision"])

    def test_energy_review_refuses_one_sided_scientific_review_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            parsed_path = root / "parsed-result.json"
            shutil.copy2(FIXTURES / "parsed_ts_result.json", parsed_path)
            review_path, _mode_path, _decision_path = self.make_energy_review(
                root, chain["candidate_path"], parsed_path
            )
            review = ADAPTER.rw.load_json(review_path)
            review["sources"]["scientific_decision"] = None
            dump(review_path, refinalize(review))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "schema rejected|supplied together"):
                ADAPTER.validate_artifact(review_path)

    def test_energy_projection_rejects_internally_inconsistent_specialist_result(self) -> None:
        mutations = (
            ("frequency count", lambda parsed: parsed.__setitem__("frequency_count", 4)),
            ("imaginary-frequency count", lambda parsed: parsed.__setitem__("raw_imaginary_frequency_count", 2)),
            ("imaginary-mode table", lambda parsed: parsed["imaginary_modes"].append(copy.deepcopy(parsed["imaginary_modes"][0]))),
            ("imaginary-mode frequency", lambda parsed: parsed["imaginary_modes"][0].__setitem__("frequency_cm-1", -251.0)),
        )
        for label, mutation in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                chain = self.make_input_chain(root)
                parsed = json.loads((FIXTURES / "parsed_ts_result.json").read_text(encoding="utf-8"))
                mutation(parsed)
                parsed_path = root / "parsed-result.json"
                dump(parsed_path, parsed)
                review_path, _, _ = self.make_energy_review(root, chain["candidate_path"], parsed_path)
                with self.assertRaisesRegex(ADAPTER.AdapterError, "internally inconsistent|differs"):
                    ADAPTER.build_energy_projection(
                        chain["candidate_path"], parsed_path, review_path,
                        root / "energy-record.json", root / "energy-lineage.json",
                    )
                self.assertFalse((root / "energy-record.json").exists())
                self.assertFalse((root / "energy-lineage.json").exists())

    def test_energy_projection_rejects_mode_review_content_not_in_parsed_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            parsed_path = root / "parsed-result.json"
            shutil.copy2(FIXTURES / "parsed_ts_result.json", parsed_path)
            review_path, mode_path, decision_path = self.make_energy_review(
                root, chain["candidate_path"], parsed_path
            )
            self.assertIsNotNone(mode_path)
            self.assertIsNotNone(decision_path)
            mode = ADAPTER.rw.load_json(mode_path)
            mode["displacements"][0]["x"] += 0.001
            dump(mode_path, mode)
            decision = ADAPTER.rw.load_json(decision_path)
            decision["mode_review_sha256"] = digest(mode_path)
            dump(decision_path, decision)
            review = ADAPTER.rw.load_json(review_path)
            review["sources"]["mode_review"] = ADAPTER.artifact_ref(mode_path, mode)
            review["sources"]["scientific_decision"] = ADAPTER.artifact_ref(decision_path, decision)
            dump(review_path, refinalize(review))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "mode-review displacements differ"):
                ADAPTER.build_energy_projection(
                    chain["candidate_path"], parsed_path, review_path,
                    root / "energy-record.json", root / "energy-lineage.json",
                )
            self.assertFalse((root / "energy-record.json").exists())
            self.assertFalse((root / "energy-lineage.json").exists())

    def test_energy_projection_rejects_rehashed_mode_geometry_forgeries(self) -> None:
        projection = {
            "pair": [1, 2],
            "equilibrium_angstrom": 0.0,
            "plus_angstrom": 0.0,
            "minus_angstrom": 0.0,
            "plus_minus_change_angstrom": 0.0,
        }
        cases = (
            ("empty displacements", lambda mode: mode.__setitem__("displacements", []), "must not be empty"),
            (
                "outside pair",
                lambda mode: mode.__setitem__(
                    "distance_projections", [{**projection, "pair": [1, 999]}]
                ),
                "outside the final geometry",
            ),
            (
                "same atom pair",
                lambda mode: mode.__setitem__(
                    "distance_projections", [{**projection, "pair": [1, 1]}]
                ),
                "not distinct",
            ),
            (
                "negative distance",
                lambda mode: mode.__setitem__(
                    "distance_projections", [
                        {
                            **projection,
                            "equilibrium_angstrom": -1.0,
                            "plus_angstrom": -1.0,
                            "minus_angstrom": -1.0,
                        }
                    ],
                ),
                "must be nonnegative",
            ),
            (
                "inconsistent projection",
                lambda mode: mode.__setitem__("distance_projections", [projection]),
                "differs from specialist displacement arithmetic",
            ),
            (
                "zero amplitude",
                lambda mode: mode.__setitem__("amplitude", 0.0),
                "positive finite number",
            ),
            (
                "negative amplitude",
                lambda mode: mode.__setitem__("amplitude", -0.1),
                "positive finite number",
            ),
        )
        for label, mutation, pattern in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                artifacts = self.make_attempt_artifacts(root)
                mode = ADAPTER.rw.load_json(artifacts["mode_path"])
                mutation(mode)
                dump(artifacts["mode_path"], mode)
                decision = ADAPTER.rw.load_json(artifacts["decision_path"])
                decision["mode_review_sha256"] = digest(artifacts["mode_path"])
                dump(artifacts["decision_path"], decision)
                review = ADAPTER.rw.load_json(artifacts["energy_review_path"])
                review["sources"]["mode_review"] = ADAPTER.artifact_ref(
                    artifacts["mode_path"], mode
                )
                review["sources"]["scientific_decision"] = ADAPTER.artifact_ref(
                    artifacts["decision_path"], decision
                )
                dump(artifacts["energy_review_path"], refinalize(review))
                with self.assertRaisesRegex(ADAPTER.AdapterError, pattern):
                    ADAPTER.build_energy_projection(
                        artifacts["chain"]["candidate_path"], artifacts["parsed_path"],
                        artifacts["energy_review_path"], root / "energy-record.json",
                        root / "energy-lineage.json",
                    )
                self.assertFalse((root / "energy-record.json").exists())
                self.assertFalse((root / "energy-lineage.json").exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            parsed = ADAPTER.rw.load_json(artifacts["parsed_path"])
            parsed["imaginary_modes"][0]["displacements"][0]["atomic_number"] = 6
            dump(artifacts["parsed_path"], parsed)
            mode = ADAPTER.rw.load_json(artifacts["mode_path"])
            mode["ts_result_sha256"] = digest(artifacts["parsed_path"])
            mode["displacements"] = copy.deepcopy(parsed["imaginary_modes"][0]["displacements"])
            dump(artifacts["mode_path"], mode)
            decision = ADAPTER.rw.load_json(artifacts["decision_path"])
            decision["ts_result_sha256"] = digest(artifacts["parsed_path"])
            decision["mode_review_sha256"] = digest(artifacts["mode_path"])
            dump(artifacts["decision_path"], decision)
            review = ADAPTER.rw.load_json(artifacts["energy_review_path"])
            review["sources"]["parsed_result"] = ADAPTER.artifact_ref(
                artifacts["parsed_path"], parsed
            )
            review["sources"]["mode_review"] = ADAPTER.artifact_ref(
                artifacts["mode_path"], mode
            )
            review["sources"]["scientific_decision"] = ADAPTER.artifact_ref(
                artifacts["decision_path"], decision
            )
            dump(artifacts["energy_review_path"], refinalize(review))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "atomic numbers differ"):
                ADAPTER.build_energy_projection(
                    artifacts["chain"]["candidate_path"], artifacts["parsed_path"],
                    artifacts["energy_review_path"], root / "energy-record.json",
                    root / "energy-lineage.json",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            parsed = ADAPTER.rw.load_json(artifacts["parsed_path"])
            parsed["imaginary_modes"][0]["displacements"].pop()
            dump(artifacts["parsed_path"], parsed)
            mode = ADAPTER.rw.load_json(artifacts["mode_path"])
            mode["ts_result_sha256"] = digest(artifacts["parsed_path"])
            mode["displacements"] = copy.deepcopy(parsed["imaginary_modes"][0]["displacements"])
            dump(artifacts["mode_path"], mode)
            decision = ADAPTER.rw.load_json(artifacts["decision_path"])
            decision["ts_result_sha256"] = digest(artifacts["parsed_path"])
            decision["mode_review_sha256"] = digest(artifacts["mode_path"])
            dump(artifacts["decision_path"], decision)
            review = ADAPTER.rw.load_json(artifacts["energy_review_path"])
            review["sources"]["parsed_result"] = ADAPTER.artifact_ref(
                artifacts["parsed_path"], parsed
            )
            review["sources"]["mode_review"] = ADAPTER.artifact_ref(
                artifacts["mode_path"], mode
            )
            review["sources"]["scientific_decision"] = ADAPTER.artifact_ref(
                artifacts["decision_path"], decision
            )
            dump(artifacts["energy_review_path"], refinalize(review))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "coverage differs"):
                ADAPTER.build_energy_projection(
                    artifacts["chain"]["candidate_path"], artifacts["parsed_path"],
                    artifacts["energy_review_path"], root / "energy-record.json",
                    root / "energy-lineage.json",
                )

    def test_energy_projection_rejects_rehashed_candidate_result_atom_order_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            parsed = ADAPTER.rw.load_json(artifacts["parsed_path"])
            parsed["final_coordinates"][0]["element"] = "C"
            parsed["final_coordinates"][0]["atomic_number"] = 6
            parsed["final_coordinates"][2]["element"] = "B"
            parsed["final_coordinates"][2]["atomic_number"] = 5
            parsed["imaginary_modes"][0]["displacements"][0]["atomic_number"] = 6
            parsed["imaginary_modes"][0]["displacements"][2]["atomic_number"] = 5
            dump(artifacts["parsed_path"], parsed)
            mode = ADAPTER.rw.load_json(artifacts["mode_path"])
            mode["ts_result_sha256"] = digest(artifacts["parsed_path"])
            mode["displacements"] = copy.deepcopy(parsed["imaginary_modes"][0]["displacements"])
            dump(artifacts["mode_path"], mode)
            decision = ADAPTER.rw.load_json(artifacts["decision_path"])
            decision["ts_result_sha256"] = digest(artifacts["parsed_path"])
            decision["mode_review_sha256"] = digest(artifacts["mode_path"])
            dump(artifacts["decision_path"], decision)
            review = ADAPTER.rw.load_json(artifacts["energy_review_path"])
            review["sources"]["parsed_result"] = ADAPTER.artifact_ref(
                artifacts["parsed_path"], parsed
            )
            review["sources"]["mode_review"] = ADAPTER.artifact_ref(
                artifacts["mode_path"], mode
            )
            review["sources"]["scientific_decision"] = ADAPTER.artifact_ref(
                artifacts["decision_path"], decision
            )
            dump(artifacts["energy_review_path"], refinalize(review))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "energy candidate"):
                ADAPTER.build_energy_projection(
                    artifacts["chain"]["candidate_path"], artifacts["parsed_path"],
                    artifacts["energy_review_path"], root / "energy-record.json",
                    root / "energy-lineage.json",
                )
            self.assertFalse((root / "energy-record.json").exists())
            self.assertFalse((root / "energy-lineage.json").exists())

    def test_validate_energy_review_rejects_role_schema_forgery(self) -> None:
        for role in ("mode_review", "scientific_decision"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                artifacts = self.make_attempt_artifacts(root)
                mode = ADAPTER.rw.load_json(artifacts["mode_path"])
                decision = ADAPTER.rw.load_json(artifacts["decision_path"])
                if role == "mode_review":
                    mode["schema"] = "totally-unrelated/1"
                    dump(artifacts["mode_path"], mode)
                    decision["mode_review_sha256"] = digest(artifacts["mode_path"])
                    dump(artifacts["decision_path"], decision)
                else:
                    decision["schema"] = "also-unrelated/1"
                    dump(artifacts["decision_path"], decision)
                review = ADAPTER.rw.load_json(artifacts["energy_review_path"])
                review["sources"]["mode_review"] = ADAPTER.artifact_ref(
                    artifacts["mode_path"], mode
                )
                review["sources"]["scientific_decision"] = ADAPTER.artifact_ref(
                    artifacts["decision_path"], decision
                )
                dump(artifacts["energy_review_path"], refinalize(review))
                with self.assertRaisesRegex(ADAPTER.AdapterError, "wrong schema"):
                    ADAPTER.validate_artifact(artifacts["energy_review_path"])

    def test_attempt_link_preserves_specialist_states_without_reclassification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            with (
                mock.patch.object(
                    ADAPTER.ts_irc,
                    "classify_ts_freq_result_facts",
                    wraps=ADAPTER.ts_irc.classify_ts_freq_result_facts,
                ) as result_classifier,
                mock.patch.object(
                    ADAPTER.ts_irc,
                    "classify_ts_freq_terminal_facts",
                    wraps=ADAPTER.ts_irc.classify_ts_freq_terminal_facts,
                ) as terminal_classifier,
                mock.patch.object(
                    ADAPTER.ts_irc,
                    "validate_mode_review_geometry",
                    wraps=ADAPTER.ts_irc.validate_mode_review_geometry,
                ) as mode_validator,
            ):
                link = self.build_attempt(root, artifacts)
            self.assertGreaterEqual(result_classifier.call_count, 1)
            self.assertGreaterEqual(terminal_classifier.call_count, 1)
            self.assertGreaterEqual(mode_validator.call_count, 1)
            self.assertEqual(link["preserved_classifications"]["terminal_outcome"], "ready_for_manual_mode_review")
            self.assertEqual(link["preserved_classifications"]["scientific_decision"], "accepted")
            self.assertEqual(link["classification_policy"], "specialist_values_preserved_without_reclassification")
            self.assertIsNone(link["artifacts"]["terminal_intake"]["payload_sha256"])
            self.assertFalse(link["calculation_ready"])

    def test_attempt_link_rejects_job_intake_result_and_decision_drift(self) -> None:
        cases = (
            (
                "job",
                lambda artifacts: dump(
                    artifacts["job_path"],
                    refinalize({**artifacts["job"], "source_job_sha256": "e" * 64}),
                ),
                "source hash differs",
            ),
            (
                "intake",
                lambda artifacts: (
                    artifacts["intake"]["artifacts"].__setitem__("input_sha256", "e" * 64),
                    dump(artifacts["intake_path"], artifacts["intake"]),
                ),
                "terminal intake input hash differs",
            ),
            (
                "result",
                lambda artifacts: (
                    artifacts["parsed"].__setitem__("log_sha256", "e" * 64),
                    dump(artifacts["parsed_path"], artifacts["parsed"]),
                ),
                "(?:mode review|decision) parsed-result hash mismatch",
            ),
            (
                "decision",
                lambda artifacts: (
                    (lambda decision: (
                        decision.__setitem__("imaginary_frequency_cm-1", -251.0),
                        dump(artifacts["decision_path"], decision),
                    ))(ADAPTER.rw.load_json(artifacts["decision_path"])),
                ),
                "imaginary frequency differs",
            ),
        )
        for label, mutation, pattern in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                artifacts = self.make_attempt_artifacts(root)
                mutation(artifacts)
                with self.assertRaisesRegex(ADAPTER.AdapterError, pattern):
                    self.build_attempt(root, artifacts)
                self.assertFalse((root / "attempt-link.json").exists())

    def test_attempt_link_rejects_terminal_facts_that_disagree_with_bound_artifacts(self) -> None:
        cases = (
            (
                "job status",
                lambda intake: intake["terminal_evidence"].__setitem__("job_state", "failed"),
                "(?:terminal outcome differs|job status differs)",
            ),
            (
                "termination counts",
                lambda intake: intake["terminal_evidence"].__setitem__("normal_termination_count", 2),
                "termination counts differ",
            ),
            (
                "scientific facts",
                lambda intake: intake["scientific_evidence"].__setitem__("optimization_completed", False),
                "(?:terminal outcome differs|scientific facts differ)",
            ),
            (
                "parsed atom count",
                lambda intake: intake["scientific_evidence"].__setitem__("atom_count", 5),
                "(?:terminal outcome differs|atom counts differ)",
            ),
            (
                "handoff atom count",
                lambda intake: intake["scientific_evidence"].__setitem__("expected_atom_count", 5),
                "(?:terminal outcome differs|atom counts differ)",
            ),
            (
                "imaginary frequencies",
                lambda intake: intake["scientific_evidence"].__setitem__("imaginary_frequencies_cm-1", [-251.0]),
                "imaginary frequencies differ",
            ),
            (
                "expected frequency coverage",
                lambda intake: intake["scientific_evidence"].__setitem__("expected_frequency_count", 4),
                "terminal outcome differs",
            ),
        )
        for label, mutation, pattern in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                artifacts = self.make_attempt_artifacts(root)
                mutation(artifacts["intake"])
                dump(artifacts["intake_path"], artifacts["intake"])
                with self.assertRaisesRegex(ADAPTER.AdapterError, pattern):
                    self.build_attempt(root, artifacts)
                self.assertFalse((root / "attempt-link.json").exists())

    def test_attempt_link_rejects_fully_rebound_forged_scientific_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            parsed = ADAPTER.rw.load_json(artifacts["parsed_path"])
            parsed.update(
                {
                    "status": "failed",
                    "normal_termination_count": 0,
                    "error_termination_count": 1,
                    "optimization_completed": False,
                    "stationary_point_found": False,
                    "first_order_saddle_candidate": False,
                    "mode_review_status": "not_eligible",
                }
            )
            dump(artifacts["parsed_path"], parsed)
            mode = ADAPTER.rw.load_json(artifacts["mode_path"])
            mode["ts_result_sha256"] = digest(artifacts["parsed_path"])
            dump(artifacts["mode_path"], mode)
            decision = ADAPTER.rw.load_json(artifacts["decision_path"])
            decision["ts_result_sha256"] = digest(artifacts["parsed_path"])
            decision["mode_review_sha256"] = digest(artifacts["mode_path"])
            dump(artifacts["decision_path"], decision)
            intake = copy.deepcopy(artifacts["intake"])
            intake["terminal_evidence"].update(
                {
                    "job_state": "failed",
                    "normal_termination_count": 0,
                    "error_termination_count": 1,
                }
            )
            intake["outcome"] = "error_or_interrupted_termination"
            intake["acceptance_status"] = "not_accepted"
            intake["next_required_artifacts"] = []
            intake["scientific_evidence"].update(
                {
                    "optimization_completed": False,
                    "stationary_point_found": False,
                    "first_order_saddle_candidate": False,
                    "mode_review_status": "not_eligible",
                }
            )
            dump(artifacts["intake_path"], intake)
            job = ADAPTER.rw.load_json(artifacts["job_path"])
            job["status"] = "failed"
            job["last_inspection_state"] = "failed"
            dump(artifacts["job_path"], refinalize(job))
            with self.assertRaisesRegex(
                ADAPTER.AdapterError,
                "mode review requires an eligible|review-eligible",
            ):
                self.build_attempt(root, artifacts)
            self.assertFalse((root / "attempt-link.json").exists())

    def test_attempt_link_rejects_rehashed_formula_preserving_atom_order_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            parsed = ADAPTER.rw.load_json(artifacts["parsed_path"])
            parsed["final_coordinates"][0]["element"] = "C"
            parsed["final_coordinates"][0]["atomic_number"] = 6
            parsed["final_coordinates"][2]["element"] = "B"
            parsed["final_coordinates"][2]["atomic_number"] = 5
            parsed["imaginary_modes"][0]["displacements"][0]["atomic_number"] = 6
            parsed["imaginary_modes"][0]["displacements"][2]["atomic_number"] = 5
            dump(artifacts["parsed_path"], parsed)
            mode = ADAPTER.rw.load_json(artifacts["mode_path"])
            mode["ts_result_sha256"] = digest(artifacts["parsed_path"])
            mode["displacements"] = copy.deepcopy(parsed["imaginary_modes"][0]["displacements"])
            dump(artifacts["mode_path"], mode)
            decision = ADAPTER.rw.load_json(artifacts["decision_path"])
            decision["ts_result_sha256"] = digest(artifacts["parsed_path"])
            decision["mode_review_sha256"] = digest(artifacts["mode_path"])
            dump(artifacts["decision_path"], decision)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "atom order or elements differ"):
                self.build_attempt(root, artifacts)
            self.assertFalse((root / "attempt-link.json").exists())

    def test_validate_artifact_recomputes_rehashed_target_and_handoff_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            ledger_path, _ = self.make_ledger(root, chain)
            target_path = root / "target-import.json"
            ADAPTER.build_target_import(
                chain["study_path"], ledger_path, target_path, "fixture_target_import"
            )
            self.assertTrue(ADAPTER.validate_artifact(target_path)["valid"])
            forged_target = ADAPTER.rw.load_json(target_path)
            blocked = next(
                target for target in forged_target["targets"]
                if target["candidate_id"] == "boron_ts_rejected"
            )
            blocked["readiness_facts"]["eligible_for_later_input_review"] = True
            blocked["readiness_facts"]["blockers"] = []
            forged_target["counts"]["eligible_for_later_input_review"] += 1
            dump(target_path, refinalize(forged_target))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "deterministic ledger-derived"):
                ADAPTER.validate_artifact(target_path)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            _input_path, handoff_path, _input_bytes, _handoff = self.build_handoff(root, chain)
            self.assertTrue(ADAPTER.validate_artifact(handoff_path)["valid"])
            forged_handoff = ADAPTER.rw.load_json(handoff_path)
            forged_handoff["identity"]["formula"] = "C2H2BN"
            dump(handoff_path, refinalize(forged_handoff))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "deterministic reviewed-source"):
                ADAPTER.validate_artifact(handoff_path)

    def test_validate_artifact_refuses_noncanonical_and_symlinked_derived_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            input_path, handoff_path, _input_bytes, _handoff = self.build_handoff(root, chain)
            handoff = ADAPTER.rw.load_json(handoff_path)
            handoff["input"]["path"] = input_path.name
            dump(handoff_path, refinalize(handoff))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "canonical repository-bound locator"):
                ADAPTER.validate_artifact(handoff_path)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            input_path, handoff_path, _input_bytes, _handoff = self.build_handoff(root, chain)
            alias = root / "alias"
            try:
                alias.symlink_to(root, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            handoff = ADAPTER.rw.load_json(handoff_path)
            handoff["input"]["path"] = str(alias / input_path.name)
            dump(handoff_path, refinalize(handoff))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "path component.*symlink"):
                ADAPTER.validate_artifact(handoff_path)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            record_path = root / "energy-record"
            lineage_path = root / "energy-lineage.json"
            ADAPTER.build_energy_projection(
                artifacts["chain"]["candidate_path"], artifacts["parsed_path"],
                artifacts["energy_review_path"], record_path, lineage_path,
            )
            self.assertTrue(ADAPTER.validate_artifact(lineage_path)["valid"])
            lineage = ADAPTER.rw.load_json(lineage_path)
            lineage["sources"]["energy_record"]["path"] = record_path.name
            dump(lineage_path, refinalize(lineage))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "canonical repository-bound locator"):
                ADAPTER.validate_artifact(lineage_path)

    def test_validate_artifact_recomputes_rehashed_energy_and_attempt_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            record_path = root / "energy-record.json"
            lineage_path = root / "energy-lineage.json"
            ADAPTER.build_energy_projection(
                artifacts["chain"]["candidate_path"], artifacts["parsed_path"],
                artifacts["energy_review_path"], record_path, lineage_path,
            )
            self.assertTrue(ADAPTER.validate_artifact(lineage_path)["valid"])
            with self.assertRaisesRegex(ADAPTER.AdapterError, "no standalone source pointers"):
                ADAPTER.validate_artifact(record_path)

            forged_record = ADAPTER.rw.load_json(record_path)
            forged_record["energy"]["electronic_energy"]["value"] = -999.0
            forged_record = refinalize(forged_record)
            dump(record_path, forged_record)
            forged_lineage = ADAPTER.rw.load_json(lineage_path)
            forged_lineage["sources"]["energy_record"] = ADAPTER.artifact_ref(
                record_path, forged_record
            )
            dump(lineage_path, refinalize(forged_lineage))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "energy record differs"):
                ADAPTER.validate_artifact(lineage_path)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            attempt_path = root / "attempt-link.json"
            attempt = self.build_attempt(root, artifacts)
            self.assertEqual(
                attempt["artifacts"]["mode_review"]["sha256"], digest(artifacts["mode_path"])
            )
            self.assertEqual(
                attempt["artifacts"]["mode_review"]["size_bytes"],
                artifacts["mode_path"].stat().st_size,
            )
            self.assertEqual(
                attempt["artifacts"]["mode_review"]["schema"], "gaussian-ts-mode-review/1"
            )
            self.assertTrue(ADAPTER.validate_artifact(attempt_path)["valid"])
            forged_attempt = ADAPTER.rw.load_json(attempt_path)
            forged_attempt["preserved_classifications"]["job_status"] = "fabricated_success"
            dump(attempt_path, refinalize(forged_attempt))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "observation-derived facts"):
                ADAPTER.validate_artifact(attempt_path)

    def test_attempt_link_refuses_rehashed_forged_nested_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            attempt_path = root / "attempt-link.json"
            self.build_attempt(root, artifacts)
            handoff = ADAPTER.rw.load_json(artifacts["manifest_path"])
            handoff["identity"]["formula"] = "FORGED"
            handoff = refinalize(handoff)
            dump(artifacts["manifest_path"], handoff)
            attempt = ADAPTER.rw.load_json(attempt_path)
            attempt["artifacts"]["input_handoff"] = ADAPTER.artifact_ref(
                artifacts["manifest_path"], handoff
            )
            dump(attempt_path, refinalize(attempt))
            with self.assertRaisesRegex(ADAPTER.AdapterError, "deterministic reviewed-source"):
                ADAPTER.validate_artifact(attempt_path)

            attempt_path.unlink()
            with self.assertRaisesRegex(ADAPTER.AdapterError, "deterministic reviewed-source"):
                self.build_attempt(root, artifacts)
            self.assertFalse(attempt_path.exists())

    def test_attempt_link_requires_decision_to_bind_exact_mode_review_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            decision = ADAPTER.rw.load_json(artifacts["decision_path"])
            decision["mode_review_sha256"] = "e" * 64
            dump(artifacts["decision_path"], decision)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "review hash mismatch"):
                self.build_attempt(root, artifacts)
            self.assertFalse((root / "attempt-link.json").exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            attempt_path = root / "attempt-link.json"
            self.build_attempt(root, artifacts)
            artifacts["mode_path"].write_bytes(artifacts["mode_path"].read_bytes() + b"\n")
            with self.assertRaisesRegex(ADAPTER.AdapterError, "artifact reference drift"):
                ADAPTER.validate_artifact(attempt_path)

    def test_validate_artifact_rechecks_referenced_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            input_path, manifest_path, _, _ = self.build_handoff(root, chain)
            input_path.write_bytes(input_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ADAPTER.AdapterError, "artifact reference drift"):
                ADAPTER.validate_artifact(manifest_path)

    def test_builders_refuse_overwrite_without_partial_companion_output(self) -> None:
        sentinel = b"existing artifact\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            chain = self.make_input_chain(root)
            ledger_path, _ = self.make_ledger(root, chain)
            output = root / "target-import.json"
            output.write_bytes(sentinel)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "overwrite"):
                ADAPTER.build_target_import(
                    chain["study_path"], ledger_path, output, "fixture_target_import"
                )
            self.assertEqual(output.read_bytes(), sentinel)
        for existing_name, absent_name in (
            ("fixture_ts.gjf", "fixture_ts.handoff.json"),
            ("fixture_ts.handoff.json", "fixture_ts.gjf"),
        ):
            with self.subTest(existing=existing_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                chain = self.make_input_chain(root)
                (root / existing_name).write_bytes(sentinel)
                with self.assertRaisesRegex(ADAPTER.AdapterError, "overwrite"):
                    self.build_handoff(root, chain)
                self.assertEqual((root / existing_name).read_bytes(), sentinel)
                self.assertFalse((root / absent_name).exists())
        for existing_name, absent_name in (
            ("energy-record.json", "energy-lineage.json"),
            ("energy-lineage.json", "energy-record.json"),
        ):
            with self.subTest(existing=existing_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                chain = self.make_input_chain(root)
                parsed_path = root / "parsed-result.json"
                shutil.copy2(FIXTURES / "parsed_ts_result.json", parsed_path)
                review_path, _, _ = self.make_energy_review(root, chain["candidate_path"], parsed_path)
                (root / existing_name).write_bytes(sentinel)
                with self.assertRaisesRegex(ADAPTER.AdapterError, "overwrite"):
                    ADAPTER.build_energy_projection(
                        chain["candidate_path"], parsed_path, review_path,
                        root / "energy-record.json", root / "energy-lineage.json",
                    )
                self.assertEqual((root / existing_name).read_bytes(), sentinel)
                self.assertFalse((root / absent_name).exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifacts = self.make_attempt_artifacts(root)
            output = root / "attempt-link.json"
            output.write_bytes(sentinel)
            with self.assertRaisesRegex(ADAPTER.AdapterError, "overwrite"):
                self.build_attempt(root, artifacts)
            self.assertEqual(output.read_bytes(), sentinel)

    def test_output_paths_reject_symlinked_ancestors_and_relative_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            try:
                linked_parent.symlink_to(real_parent, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            target = linked_parent / "must-not-create" / "artifact.json"
            with self.assertRaisesRegex(ADAPTER.AdapterError, "ancestor.*symlink"):
                ADAPTER._output_path(target, "adversarial output")
            self.assertFalse((real_parent / "must-not-create").exists())
            self.assertFalse(target.exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            invocation_root = root / "invocation-root"
            invocation_root.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(invocation_root)
                with self.assertRaisesRegex(ADAPTER.AdapterError, "lexical root"):
                    ADAPTER._output_path(Path("..") / "escaped" / "artifact.json", "adversarial output")
            finally:
                os.chdir(previous)
            self.assertFalse((root / "escaped").exists())

    def test_portable_paths_are_relative_only_inside_repository_root(self) -> None:
        expected_module_path = str(MODULE_PATH.resolve().relative_to(ROOT.resolve()))
        self.assertEqual(ADAPTER._portable(MODULE_PATH), expected_module_path)
        with tempfile.TemporaryDirectory() as tmp:
            external_root = Path(tmp).resolve()
            external = external_root / "external.json"
            dump(external, {"schema": "external-fixture/1"})
            self.assertTrue(Path(ADAPTER._portable(external)).is_absolute())
            previous = Path.cwd()
            try:
                os.chdir(external_root)
                self.assertEqual(ADAPTER._portable(MODULE_PATH), expected_module_path)
            finally:
                os.chdir(previous)
            with tempfile.TemporaryDirectory(dir=ROOT) as local_tmp:
                local = Path(local_tmp).resolve() / "local.json"
                dump(local, {"schema": "local-fixture/1"})
                portable = ADAPTER._portable(local)
                self.assertFalse(Path(portable).is_absolute())
                self.assertEqual((ROOT / portable).resolve(), local)

    def test_strict_json_symlink_unknown_fields_and_no_live_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema":"gaussian-energy-review/1","schema":"duplicate"}\n', encoding="utf-8")
            completed = subprocess.run([sys.executable, str(MODULE_PATH), "validate", str(duplicate)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("duplicate JSON", completed.stderr)
            for index, token in enumerate(("NaN", "Infinity", "-Infinity"), start=1):
                nonfinite = root / f"nonfinite-{index}.json"
                nonfinite.write_text(
                    f'{{"schema":"gaussian-energy-review/1","value":{token}}}\n',
                    encoding="utf-8",
                )
                completed = subprocess.run(
                    [sys.executable, str(MODULE_PATH), "validate", str(nonfinite)],
                    cwd=ROOT, text=True, capture_output=True, check=False,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("non-standard JSON", completed.stderr)
            symlink = root / "symlink.json"
            try:
                symlink.symlink_to(duplicate)
            except OSError:
                self.skipTest("symlinks unavailable")
            completed = subprocess.run([sys.executable, str(MODULE_PATH), "validate", str(symlink)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("symlink", completed.stderr)
        source = MODULE_PATH.read_text(encoding="utf-8")
        for raw_marker in ("SCF Done:", "Frequencies --", "Normal termination of Gaussian"):
            self.assertNotIn(raw_marker, source)
        for live_call in ("subprocess.run", "qsub", "ssh ", "create_server_directory"):
            self.assertNotIn(live_call, source)
        help_text = subprocess.run([sys.executable, str(MODULE_PATH), "--help"], cwd=ROOT, text=True, capture_output=True, check=False).stdout
        for forbidden_command in ("submit", "stage", "fetch", "cancel", "cleanup"):
            self.assertNotIn("{" + forbidden_command, help_text)


if __name__ == "__main__":
    unittest.main()
