#!/usr/bin/env python3
"""Pure-offline tests for the reaction thermochemistry readiness audit."""

from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "thermochemistry_readiness.py"
sys.path.insert(0, str(TOOL.parent))
try:
    SPEC = importlib.util.spec_from_file_location("thermochemistry_readiness_test", TOOL)
    assert SPEC and SPEC.loader
    MODULE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(MODULE)
finally:
    sys.path.pop(0)

SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SCHEMA_SPEC = importlib.util.spec_from_file_location("thermochemistry_readiness_schema", SCHEMA_VALIDATOR_PATH)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA_VALIDATOR = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA_VALIDATOR)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def artifact_ref(path: Path, root: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "schema": document["schema"],
        "payload_sha256": document["payload_sha256"],
    }


def make_request(root: Path, sources: list[dict[str, object]], name: str = "request.json") -> Path:
    value = MODULE.rw.finalize_artifact({
        "schema": MODULE.REQUEST_SCHEMA,
        "audit_id": "thermochemistry_readiness_fixture",
        "study_id": "study_fixture",
        "owner_artifacts": sources,
        "reviewer": "offline fixture reviewer",
        "reviewed_at": "2026-07-17T00:00:00Z",
        "review_notes": ["Readiness audit only; no barrier calculation."],
        "calculation_ready": False,
        "no_submission_authorization": True,
    })
    path = root / name
    write_json(path, value)
    return path


class ThermochemistryReadinessTests(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(TOOL), *args], cwd=ROOT, text=True, capture_output=True, check=False)

    def test_closed_schemas_and_positive_blocker_artifact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            request = make_request(root, [])
            output = root / "audit.json"
            result = self.run_cli("build", request.name, "--root", str(root), "--output", output.name)
            self.assertEqual(result.returncode, 0, result.stderr)
            audit = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(audit["formal_comparison_ready"])
            self.assertFalse(audit["formal_barrier_available"])
            self.assertFalse(audit["arithmetic_performed"])
            self.assertGreaterEqual(len(audit["blockers"]), 6)
            replay = self.run_cli("validate", output.name, "--root", str(root))
            self.assertEqual(replay.returncode, 0, replay.stderr)

            for name, document in (
                ("thermochemistry-readiness-request.schema.json", json.loads(request.read_text(encoding="utf-8"))),
                ("thermochemistry-readiness-audit.schema.json", audit),
            ):
                schema = json.loads((ROOT / "contracts" / "reaction-workflow" / name).read_text(encoding="utf-8"))
                SCHEMA_VALIDATOR.validate_schema_document(schema)
                SCHEMA_VALIDATOR._validate_schema_instance(document, schema, schema)

    def test_immutable_publish_never_overwrites_existing_or_concurrent_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            request = make_request(root, [])
            existing = root / "existing.json"
            existing.write_bytes(b"sentinel\n")
            result = self.run_cli("build", request.name, "--root", str(root), "--output", existing.name)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(existing.read_bytes(), b"sentinel\n")

            concurrent_output = root / "concurrent.json"
            def writer() -> str:
                try:
                    MODULE.build(root, request, concurrent_output)
                    return "published"
                except MODULE.rw.OfflineError as exc:
                    self.assertIn("refusing to overwrite", str(exc))
                    return "blocked"

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: writer(), range(2)))
            self.assertEqual(sorted(outcomes), ["blocked", "published"])
            audit = json.loads(concurrent_output.read_text(encoding="utf-8"))
            self.assertEqual(audit["schema"], MODULE.AUDIT_SCHEMA)
            leftovers = list(root.glob(".concurrent.json.*.tmp"))
            self.assertEqual(leftovers, [])

    def test_forged_allowed_schema_and_authority_cache_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake_gate = MODULE.rw.finalize_artifact({
                "schema": "gaussian-scientific-maturity-gate/1",
                "minimum_gates": [{"minimum_id": "minimum_fake", "accepted": True}],
            })
            gate_path = root / "fake-gate.json"
            write_json(gate_path, fake_gate)
            source = {"source_id": "fake_minimum_owner", "role": "minimum_evidence", "artifact": artifact_ref(gate_path, root)}
            request = make_request(root, [source])
            result = self.run_cli("build", request.name, "--root", str(root), "--output", "audit.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertRegex(result.stderr, "unknown or missing fields|minimum_gates|safety constants")

            request_value = json.loads(request.read_text(encoding="utf-8"))
            request_value["validator_id"] = "scientific_maturity.validate_gate"
            request_value = MODULE.rw.finalize_artifact(request_value)
            write_json(request, request_value)
            result = self.run_cli("build", request.name, "--root", str(root), "--output", "audit.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown or missing fields", result.stderr)

    def test_actual_maturity_v1_owner_replays_but_requires_readiness_repackage(self) -> None:
        maturity_path = ROOT / "tests" / "test_scientific_maturity.py"
        spec = importlib.util.spec_from_file_location("thermochemistry_readiness_maturity_fixture", maturity_path)
        assert spec and spec.loader
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            helper = fixture.ScientificMaturityTests("test_two_accepted_minima_open_low_cost_ts_pilot_but_preserve_owner_gates")
            _plan, gate_path = helper.build_gate(root)
            validated_gate = MODULE._owner_validate(gate_path, "gaussian-scientific-maturity-gate/1")
            self.assertEqual(validated_gate["schema"], "gaussian-scientific-maturity-gate/1")
            request = make_request(root, [{"source_id": "minimum_gate_v1", "role": "minimum_evidence", "artifact": artifact_ref(gate_path, root)}])
            output = root / "audit.json"
            result = self.run_cli("build", request.name, "--root", str(root), "--output", output.name)
            self.assertNotEqual(result.returncode, 0)
            self.assertRegex(result.stderr, "must be package-relative|hash drift|parent traversal")
            # The historical synthetic builder is scientifically replayable but
            # contains older absolute nested provenance.  Bypassing only the new
            # package audit proves /1 still receives the fixed blocker after the
            # actual public owner validator runs; production never bypasses it.
            with mock.patch.object(MODULE, "_audit_transitive_refs", return_value=None):
                MODULE.build(root, request, output)
            audit = json.loads(output.read_text(encoding="utf-8"))
            codes = {item["code"] for item in audit["blockers"]}
            self.assertIn("minimum_owner_evidence_v2_required", codes)
            self.assertEqual(audit["owner_replays"][0]["validator_implementation"], "scientific_maturity.validate_gate")

    def test_actual_maturity_v2_replays_and_preserves_all_formal_readiness_blockers(self) -> None:
        maturity_path = ROOT / "tests" / "test_scientific_maturity_v2.py"
        spec = importlib.util.spec_from_file_location("thermochemistry_readiness_maturity_v2_fixture", maturity_path)
        assert spec and spec.loader
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            helper = fixture.ScientificMaturityV2Tests("test_positive_pilot_roundtrip_schemas_and_v1_compatibility")
            helper.setUp()
            _, base_gate_path, base_review, mechanism = helper.base_context(root)
            review = helper.review_v2(root, base_gate_path, base_review, mechanism)
            _, _, gate_path = helper.build_overlay(root, review, base_gate_path)
            validated = MODULE._owner_validate(gate_path, "gaussian-scientific-maturity-gate/2")
            self.assertEqual(validated["schema"], "gaussian-scientific-maturity-gate/2")
            source = {
                "source_id": "minimum_gate_v2", "role": "minimum_evidence",
                "artifact": artifact_ref(gate_path, root),
            }
            request = make_request(root, [source])
            output = root / "audit.json"
            # Older nested owner fixtures are not packaged for readiness; only
            # bypass that portability audit here after the actual /2 validator replay.
            with mock.patch.object(MODULE, "_audit_transitive_refs", return_value=None):
                MODULE.build(root, request, output)
            audit = json.loads(output.read_text(encoding="utf-8"))
            codes = {item["code"] for item in audit["blockers"]}
            self.assertTrue({
                "minimum_candidate_input_result_lineage_unavailable_v2",
                "exact_owner_ts_mode_artifact_v2_required",
                "complete_owner_thermochemistry_evidence_v2_required",
                "ts_owner_chain_missing",
                "energy_lineage_missing",
            }.issubset(codes))
            self.assertEqual(
                audit["owner_replays"][0]["validator_implementation"],
                "scientific_maturity_v2.validate_gate",
            )
            self.assertFalse(audit["formal_comparison_ready"])
            self.assertFalse(audit["formal_barrier_available"])
            self.assertFalse(audit["arithmetic_performed"])

    def test_actual_attempt_owner_replays_but_requires_readiness_repackage(self) -> None:
        adapter_path = ROOT / "tests" / "test_calculation_artifacts.py"
        spec = importlib.util.spec_from_file_location("thermochemistry_readiness_attempt_fixture", adapter_path)
        assert spec and spec.loader
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            package = Path(temporary).resolve()
            helper = fixture.CalculationArtifactTests("test_attempt_link_preserves_specialist_states_without_reclassification")
            artifacts = helper.make_attempt_artifacts(package)
            helper.build_attempt(package, artifacts)
            attempt_path = package / "attempt-link.json"
            validated_attempt = MODULE._owner_validate(attempt_path, "gaussian-calculation-attempt-link/1")
            self.assertEqual(validated_attempt["schema"], "gaussian-calculation-attempt-link/1")
            source = {"source_id": "attempt_owner", "role": "ts_attempt", "artifact": artifact_ref(attempt_path, ROOT)}
            request = make_request(package, [source])
            output = package / "audit.json"
            result = self.run_cli("build", request.relative_to(ROOT).as_posix(), "--root", str(ROOT), "--output", output.relative_to(ROOT).as_posix())
            self.assertNotEqual(result.returncode, 0)
            self.assertRegex(result.stderr, "must be package-relative|hash drift|parent traversal")
            blockers = MODULE._ts_readiness_blockers(ROOT, {
                "ts_attempt": {"source_id": "attempt_owner", "path": attempt_path, "document": validated_attempt}
            })
            self.assertEqual([item["code"] for item in blockers], ["attempt_link_only_ts"])

    def test_transitive_refs_reject_absolute_traversal_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            owner = root / "owner.json"
            target = root / "data" / "result.json"
            target.parent.mkdir()
            write_json(owner, {"schema": "owner/1"})
            write_json(target, {"schema": "result/1"})
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            cases = [
                ({"path": str(target), "sha256": digest}, "package-relative"),
                ({"path": "../escape.json", "sha256": digest}, "parent traversal"),
            ]
            for candidate, message in cases:
                with self.subTest(message=message), self.assertRaisesRegex(MODULE.rw.OfflineError, message):
                    MODULE._resolve_transitive_ref(root, owner, candidate, "owner result")
            link = root / "linked-result.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(MODULE.rw.OfflineError, "symlink"):
                MODULE._resolve_transitive_ref(root, owner, {"path": link.name, "sha256": digest}, "owner result")

    def test_wrong_exact_ts_result_hash_becomes_structured_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            attempt_path = root / "attempt.json"
            path_path = root / "acceptance.json"
            result_a = root / "result-a.json"
            result_b = root / "result-b.json"
            write_json(result_a, {"energy": -1.0})
            write_json(result_b, {"energy": -2.0})
            ref_a = {"path": result_a.name, "sha256": hashlib.sha256(result_a.read_bytes()).hexdigest()}
            ref_b = {"path": result_b.name, "sha256": hashlib.sha256(result_b.read_bytes()).hexdigest()}
            attempt_doc = {"artifacts": {"parsed_result": ref_a}}
            path_doc = {"ts_result": ref_b}
            write_json(attempt_path, attempt_doc); write_json(path_path, path_doc)
            blocker = MODULE._exact_ts_result_blocker(
                root,
                {"source_id": "attempt_owner", "path": attempt_path, "document": attempt_doc},
                {"source_id": "path_owner", "path": path_path, "document": path_doc},
            )
            self.assertIsNotNone(blocker)
            self.assertEqual(blocker["code"], "ts_result_hash_mismatch")

    def test_role_schema_swap_unknown_schema_and_help_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            owner = MODULE.rw.finalize_artifact({"schema": "gaussian-energy-lineage/1", "status": "blocked"})
            owner_path = root / "owner.json"
            write_json(owner_path, owner)
            source = {"source_id": "swapped_owner", "role": "ts_attempt", "artifact": artifact_ref(owner_path, root)}
            request = make_request(root, [source])
            result = self.run_cli("build", request.name, "--root", str(root), "--output", "audit.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot consume owner schema", result.stderr)
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("no barrier arithmetic or", help_result.stdout)
        self.assertIn("live action", help_result.stdout)
        source_text = TOOL.read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source_text)

    def test_fixture_catalog_names_positive_and_required_negative_cases(self) -> None:
        catalog = json.loads((ROOT / "tests" / "fixtures" / "reaction_workflow" / "thermochemistry_readiness_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["positive_case"]["output_kind"], "structured_blocker_audit")
        required = {"absolute_transitive_ref", "parent_traversal", "symlink", "forged_allowed_schema", "maturity_v1_minimum", "attempt_link_only_ts", "wrong_exact_ts_result_hash"}
        self.assertTrue(required.issubset({item["case_id"] for item in catalog["negative_cases"]}))


if __name__ == "__main__":
    unittest.main()
