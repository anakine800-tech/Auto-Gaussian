#!/usr/bin/env python3
"""Offline regression tests for strict scientific-closure lineage gates."""
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).parents[1]


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


LOG = module("closure_gaussian_log_test", ROOT / "skills/auto-g16-rtwin-pbs/scripts/gaussian_log.py")
TS = module("closure_ts_test", ROOT / "skills/auto-g16-ts-irc/scripts/ts_irc.py")
LINEAGE = module("closure_lineage_test", ROOT / "skills/auto-g16-reaction-workflow/scripts/scientific_closure_lineage.py")
SCHEMA_VALIDATOR = module("closure_schema_validator_test", ROOT / "scripts/validate_asymmetric_contract.py")


def water_log(frequency_line: str = " Frequencies --  100.0 200.0 300.0") -> str:
    return (
        " Gaussian 16, Revision C.01,\n"
        " SCF Done:  E(RHF) =  -75.000000 A.U.\n"
        " Optimization completed.\n Stationary point found.\n"
        " Standard orientation:\n ----------------------------------------\n header\n ----------------------------------------\n"
        " 1 8 0 0.000000 0.000000 0.000000\n"
        " 2 1 0 0.950000 0.000000 0.000000\n"
        " 3 1 0 -0.250000 0.920000 0.000000\n"
        " ----------------------------------------\n"
        f"{frequency_line}\n"
        " Red. masses -- 1.0 1.0 1.0\n"
        " Atom AN X Y Z X Y Z X Y Z\n"
        " 1 8 0.1 0 0 0 0.1 0 0 0 0.1\n"
        " 2 1 0.1 0 0 0 0.1 0 0 0 0.1\n"
        " 3 1 0.1 0 0 0 0.1 0 0 0 0.1\n"
        " Thermal correction to Gibbs Free Energy= 0.010000\n"
        " Normal termination of Gaussian\n Normal termination of Gaussian\n Normal termination of Gaussian\n"
    )


def ts_execution_sources(root: Path, log_path: Path) -> dict[str, Path]:
    input_path = root / "water-ts.gjf"; input_path.write_text("#p hf/sto-3g opt=(ts,calcfc) freq\n\nTS\n\n0 1\nO 0 0 0\nH .95 0 0\nH -.25 .92 0\n\n")
    family_path = root / "family.json"; family_path.write_text(json.dumps({"schema": TS.SCHEMA_V2, "pilot": False, "mechanism_edge_id": "edge_water"}))
    project, job_id, attempt_id = "waterts", "123.master", "qsub-attempt-fixture"
    text = log_path.read_text()
    inspection = {
        "schema": "gaussian-job-inspection/2", "project": project, "job_id": job_id,
        "state": "completed", "collected_at": "2026-07-19T12:00:00Z", "source": "single_remote_read_only_snapshot",
        "freshness": "fresh", "transport_classification": "success", "transport_returncode": 0,
        "termination_counts_known": True, "evidence_conflict": False, "process_alive": False,
        "log_size": log_path.stat().st_size, "full_normal_termination_count": text.count("Normal termination of Gaussian"),
        "full_error_termination_count": text.count("Error termination"),
    }
    inspection["evidence_sha256"] = TS._transport_digest(inspection)
    receipt = {
        "schema": "gaussian-terminal-inspection-receipt/1", "project": project, "job_id": job_id,
        "input_stem": input_path.stem, "input_sha256": TS.sha256(input_path), "attempt_id": attempt_id,
        "terminal_state": "completed", "collected_at": inspection["collected_at"],
        "inspection_evidence_sha256": inspection["evidence_sha256"], "inspection": inspection,
        "scientific_acceptance": False,
    }
    receipt["receipt_sha256"] = TS._transport_digest(receipt)
    receipt_path = root / "terminal-inspection.json"; receipt_path.write_text(json.dumps(receipt))
    digest = TS.sha256(log_path)
    snapshot = {
        "schema": "gaussian-fetch-snapshot/1", "project": project, "job_id": job_id,
        "input_stem": input_path.stem, "input_sha256": TS.sha256(input_path), "snapshot_complete": True,
        "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "per_hop_sha256_verified": True,
        "exact_log": log_path.name,
        "artifacts": {log_path.name: {"sha256": digest, "size": log_path.stat().st_size}},
        "per_hop": {log_path.name: {"server_sha256": digest, "rtwin_sha256": digest, "mac_sha256": digest, "size": log_path.stat().st_size}},
    }
    snapshot["payload_sha256"] = TS._transport_digest(snapshot)
    snapshot_path = root / "transfer.json"; snapshot_path.write_text(json.dumps(snapshot))
    job = {
        "schema": "gaussian-rtwin-pbs/1", "project": project, "job_id": job_id, "status": "completed",
        "results_fetched": True, "input_sha256": TS.sha256(input_path), "execution_batch": {"attempt_id": attempt_id},
        "terminal_inspection_receipt_sha256": receipt["receipt_sha256"],
        "fetch_snapshot_sha256": TS.sha256(snapshot_path), "fetch_snapshot_size": snapshot_path.stat().st_size,
    }
    job_path = root / "job.json"; job_path.write_text(json.dumps(job))
    return {"family": family_path, "input": input_path, "job": job_path, "terminal_inspection_receipt": receipt_path, "fetch_snapshot": snapshot_path}


class ScientificClosureLineageTests(unittest.TestCase):
    def test_new_contract_schemas_use_supported_offline_subset(self) -> None:
        names = (
            "endpoint-structure-review.schema.json", "minimum-lineage-handoff.schema.json",
            "minimum-lineage-handoff-v2.schema.json",
            "ts-irc-path-acceptance-v2.schema.json", "ts-freq-result-v2.schema.json",
            "fragment-endpoint-validation-v2.schema.json",
        )
        for name in names:
            schema = json.loads((ROOT / "contracts/reaction-workflow" / name).read_text())
            SCHEMA_VALIDATOR.validate_schema_document(schema)

    def test_complete_frequency_gate_uses_exact_atom_count_and_linearity(self) -> None:
        complete = LOG.analyze_workflow_log_text(water_log(), temperature_k=298.15, standard_state="1M", expected_stages=3)
        self.assertEqual(complete["expected_frequency_count"], 3)
        self.assertEqual(complete["linearity"], "nonlinear")
        self.assertTrue(complete["frequency_parse_complete"])
        self.assertTrue(complete["frequency_complete"])
        self.assertTrue(complete["minimum_validated"])

        truncated = LOG.analyze_workflow_log_text(water_log(" Frequencies -- 100.0 200.0"), temperature_k=298.15, standard_state="1M", expected_stages=3)
        self.assertFalse(truncated["frequency_complete"])
        self.assertFalse(truncated["minimum_validated"])

        damaged = LOG.analyze_workflow_log_text(water_log(" Frequencies -- 100.0 BROKEN 200.0 300.0"), temperature_k=298.15, standard_state="1M", expected_stages=3)
        self.assertEqual(damaged["frequency_count"], 3)
        self.assertFalse(damaged["frequency_parse_complete"])
        self.assertEqual(damaged["frequency_parse_diagnostics"][0]["code"], "malformed_frequency_token")
        self.assertFalse(damaged["minimum_validated"])

    def test_single_stage_endpoint_opt_freq_is_complete_only_with_full_minimum_evidence(self) -> None:
        single = water_log().replace(" Normal termination of Gaussian\n Normal termination of Gaussian\n Normal termination of Gaussian\n", " Normal termination of Gaussian\n")
        accepted = LOG.analyze_workflow_log_text(single, temperature_k=298.15, standard_state="1M", expected_stages=1)
        self.assertTrue(accepted["workflow_success"])
        self.assertTrue(accepted["minimum_validated"])
        wrong_stage = LOG.analyze_workflow_log_text(single, temperature_k=298.15, standard_state="1M", expected_stages=2)
        self.assertFalse(wrong_stage["workflow_success"])
        for text in (
            single.replace(" Frequencies --  100.0 200.0 300.0", " Frequencies -- 100.0 200.0"),
            single.replace(" Frequencies --  100.0 200.0 300.0", " Frequencies -- 100.0 BROKEN 300.0"),
            single.replace(" Frequencies --  100.0 200.0 300.0", " Frequencies -- -100.0 200.0 300.0"),
        ):
            with self.subTest(text=text.split("Frequencies --", 1)[1].splitlines()[0]):
                self.assertFalse(LOG.analyze_workflow_log_text(text, temperature_k=298.15, standard_state="1M", expected_stages=1)["minimum_validated"])

    def test_source_bound_ts_result_replays_log_and_rejects_damage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_path = root / "water-ts.log"; log_path.write_text(water_log(" Frequencies -- -100.0 200.0 300.0"))
            result_path = root / "result.json"
            result = TS.build_ts_result_v2(log_path, result_path, ts_execution_sources(root, log_path))
            self.assertEqual(result["source_log"]["size_bytes"], log_path.stat().st_size)
            self.assertEqual(result["parser"]["schema"], "auto-g16-ts-irc-parser/2")
            self.assertTrue(result["frequency_parse_complete"])
            TS.validate_ts_result_v2(result, result_path)
            log_path.write_text(log_path.read_text().replace("300.0", "BROKEN"))
            with self.assertRaisesRegex(ValueError, "reference changed"):
                TS.validate_ts_result_v2(result, result_path)

        modes, diagnostics = TS.parse_modes(water_log(" Frequencies -- -100.0 NaN 300.0"))
        self.assertEqual(modes, [])
        self.assertTrue(any("non-finite" in item for item in diagnostics))

    def test_closure_paths_reject_leaf_and_intermediate_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            real_dir = root / "real"; real_dir.mkdir()
            source = real_dir / "source.log"; source.write_text(water_log())
            directory_link = root / "linked"; directory_link.symlink_to(real_dir, target_is_directory=True)
            leaf_link = root / "leaf.log"; leaf_link.symlink_to(source)

            for relative in ("linked/source.log", "leaf.log"):
                with self.subTest(owner="minimum", relative=relative):
                    with self.assertRaisesRegex(LINEAGE.LineageError, "path component must not be a symlink"):
                        LINEAGE.safe_file(root, relative, "minimum source")
                    with self.assertRaisesRegex(LINEAGE.LineageError, "path component must not be a symlink"):
                        LINEAGE.reference(root / relative, root)
                with self.subTest(owner="ts", relative=relative):
                    with self.assertRaisesRegex(ValueError, "path component must not be a symlink"):
                        TS._closure_local_ref(root / relative, root, "TS source")
                    reference = {"path": relative, "sha256": TS.sha256(source), "size_bytes": source.stat().st_size}
                    with self.assertRaisesRegex(ValueError, "path component must not be a symlink"):
                        TS._closure_resolve_local_ref(reference, root / "owner.json", "TS source")

    def test_atomic_publish_preserves_existing_and_concurrent_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            existing = root / "existing.json"; existing.write_bytes(b"sentinel\n")
            with self.assertRaisesRegex(LINEAGE.LineageError, "concurrent or overwrite"):
                LINEAGE.publish_json_exclusive(existing, {"owner": "minimum"}, lambda path: json.loads(path.read_text()))
            self.assertEqual(existing.read_bytes(), b"sentinel\n")

            concurrent_target = root / "concurrent.json"
            def fail_after_concurrent_publish(_: Path) -> dict:
                concurrent_target.write_bytes(b"concurrent writer\n")
                raise LINEAGE.LineageError("synthetic validation failure")
            with self.assertRaisesRegex(LINEAGE.LineageError, "synthetic validation failure"):
                LINEAGE.publish_json_exclusive(concurrent_target, {"owner": "minimum"}, fail_after_concurrent_publish)
            self.assertEqual(concurrent_target.read_bytes(), b"concurrent writer\n")
            self.assertEqual(list(root.glob(".concurrent.json.*.tmp")), [])

            ts_target = root / "ts-concurrent.json"
            def fail_ts_validation(_: Path) -> dict:
                ts_target.write_bytes(b"TS concurrent writer\n")
                raise ValueError("synthetic TS validation failure")
            with self.assertRaisesRegex(ValueError, "synthetic TS validation failure"):
                TS._publish_json_exclusive(ts_target, {"owner": "ts"}, fail_ts_validation)
            self.assertEqual(ts_target.read_bytes(), b"TS concurrent writer\n")
            self.assertEqual(list(root.glob(".ts-concurrent.json.*.tmp")), [])

    def test_ts_result_v2_concurrent_publication_has_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            log_path = root / "water-ts.log"; log_path.write_text(water_log(" Frequencies -- -100.0 200.0 300.0"))
            output = root / "result.json"
            sources = ts_execution_sources(root, log_path)
            barrier = threading.Barrier(2)
            original = TS._publish_json_exclusive

            def gated_publish(*args, **kwargs):
                barrier.wait(timeout=5)
                return original(*args, **kwargs)

            def writer() -> str:
                try:
                    TS.build_ts_result_v2(log_path, output, sources)
                    return "published"
                except ValueError as exc:
                    self.assertIn("concurrent or overwrite", str(exc))
                    return "blocked"

            with mock.patch.object(TS, "_publish_json_exclusive", side_effect=gated_publish):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes = list(pool.map(lambda _: writer(), range(2)))
            self.assertEqual(sorted(outcomes), ["blocked", "published"])
            TS.validate_ts_result_v2(json.loads(output.read_text()), output)
            self.assertEqual(list(root.glob(".result.json.*.tmp")), [])

            immutable_bytes = output.read_bytes()
            with self.assertRaisesRegex(ValueError, "concurrent or overwrite"):
                TS.build_ts_result_v2(log_path, output, sources)
            self.assertEqual(output.read_bytes(), immutable_bytes)

    def test_ts_result_v2_negative_evidence_schema_roundtrip_and_consumer_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); log_path = root / "damaged.log"; log_path.write_text("Gaussian 16, Revision C.01\nError termination\n")
            result_path = root / "negative.json"
            result = TS.build_ts_result_v2(log_path, result_path)
            self.assertEqual((result["atom_count"], result["linearity"], result["expected_frequency_count"]), (0, "undetermined", None))
            schema = json.loads((ROOT / "contracts/reaction-workflow/ts-freq-result-v2.schema.json").read_text())
            SCHEMA_VALIDATOR._validate_schema_instance(result, schema, schema)
            TS.validate_ts_result_v2(result, result_path)
            with self.assertRaisesRegex(ValueError, "negative, incomplete"):
                TS.require_accepted_ts_result_v2(result, result_path)

    def test_analyze_ts_cli_requires_complete_execution_chain_for_positive_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); log_path = root / "ts.log"; log_path.write_text(water_log(" Frequencies -- -100.0 200.0 300.0"))
            sources = ts_execution_sources(root, log_path); output = root / "cli-result.json"
            command = ["python3", str(ROOT / "skills/auto-g16-ts-irc/scripts/ts_irc.py"), "analyze-ts", str(log_path), "--output", str(output)]
            for key, value in sources.items():
                command.extend(["--" + key.replace("_", "-"), str(value)])
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            TS.require_accepted_ts_result_v2(json.loads(output.read_text()), output)
            missing = root / "missing.json"
            incomplete_command = command[:-2] + ["--output", str(missing)] if command[-2] != "--output" else command
            incomplete_command = [item for index, item in enumerate(command) if index not in {command.index("--fetch-snapshot"), command.index("--fetch-snapshot") + 1}]
            incomplete_command[incomplete_command.index(str(output))] = str(missing)
            rejected = subprocess.run(incomplete_command, capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("provide family/input/job/terminal receipt/fetch snapshot together", rejected.stderr + rejected.stdout)

    def test_fragment_v2_replays_each_full_log_and_rejects_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projects = ("frag_a", "frag_b")
            plan = {
                "schema": "gaussian-irc-fragment-endpoint-plan/1", "status": "planned_not_submitted",
                "chemical_side": "product", "fragments": [],
            }
            results: dict[str, Path] = {}; jobs: dict[str, Path] = {}
            logs: dict[str, Path] = {}; checkpoints: dict[str, Path] = {}
            for index, project in enumerate(projects, start=1):
                input_sha = str(index) * 64
                plan["fragments"].append({
                    "project": project, "identity": f"synthetic fragment {index}", "formula": "H2O",
                    "atom_count": 3, "element_order": ["O", "H", "H"], "input_sha256": input_sha,
                })
                log_path = root / f"{project}.log"; log_path.write_text(water_log())
                result_path = root / f"{project}.result.json"; result_path.write_text(json.dumps(LOG.analyze_log_text(log_path.read_text())))
                job_path = root / f"{project}.job.json"; job_path.write_text(json.dumps({
                    "schema": "gaussian-rtwin-pbs/1", "project": project, "job_id": f"{index}.master",
                    "status": "completed", "results_fetched": True, "input_sha256": input_sha,
                }))
                checkpoint = root / f"{project}.chk"; checkpoint.write_bytes(f"synthetic {project}".encode())
                results[project] = result_path; jobs[project] = job_path; logs[project] = log_path; checkpoints[project] = checkpoint
            plan_path = root / "plan.json"; plan_path.write_text(json.dumps(plan))
            artifact = TS.audit_fragment_endpoint_results_v2(plan_path, results, jobs, logs, checkpoints, root / "accepted.json")
            self.assertEqual(artifact["validator"], TS.PARSER_ID)
            self.assertTrue(all(item["frequency_count"] == item["expected_frequency_count"] == 3 for item in artifact["fragments"]))
            TS.validate_fragment_endpoint_results_v2(root / "accepted.json")
            forged = json.loads(json.dumps(artifact)); forged["fragments"][0]["minimum_accepted"] = False; forged["payload_sha256"] = TS._payload_sha256(forged)
            forged_path = root / "forged.json"; forged_path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, "owner replay"):
                TS.validate_fragment_endpoint_results_v2(forged_path)

            logs["frag_b"].write_text(water_log(" Frequencies -- 100.0 200.0"))
            with self.assertRaisesRegex(ValueError, "reference changed"):
                TS.validate_fragment_endpoint_results_v2(root / "accepted.json")
            results["frag_b"].write_text(json.dumps(LOG.analyze_log_text(logs["frag_b"].read_text())))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                TS.audit_fragment_endpoint_results_v2(plan_path, results, jobs, logs, checkpoints, root / "rejected.json")

    def test_selection_receipt_is_not_input_or_submission_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "candidate.gjf"; input_path.write_text("#p hf/sto-3g\n\nX\n\n0 1\nH 0 0 0\n\n")
            xyz = root / "candidate.xyz"; xyz.write_text("1\nX\nH 0 0 0\n")
            ensemble = root / "source_ensemble.json"; ensemble.write_text("{}\n")
            receipt = {
                "schema": LINEAGE.SELECTION_SCHEMA, "candidate_only": True, "calculation_ready": False,
                "no_submission_authorization": True, "selection_is_not_authorization": True,
                "workflow_states": {"human_selected": True, "input_draft_generated": True, "exact_input_approved": False, "submission_authorized": False, "result_accepted": False},
                "selection": {"ensemble": ensemble.name, "ensemble_sha256": LINEAGE.file_sha256(ensemble), "ensemble_size_bytes": ensemble.stat().st_size},
                "gaussian_input": input_path.name, "gaussian_input_sha256": LINEAGE.file_sha256(input_path), "gaussian_input_size_bytes": input_path.stat().st_size,
                "xyz_coordinates": xyz.name, "xyz_sha256": LINEAGE.file_sha256(xyz), "xyz_size_bytes": xyz.stat().st_size,
            }
            path = root / "selection.json"; path.write_text(json.dumps(receipt))
            LINEAGE.validate_selection_receipt(path)
            receipt["workflow_states"]["exact_input_approved"] = True
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(LINEAGE.LineageError, "conflates"):
                LINEAGE.validate_selection_receipt(path)

    def test_new_lineage_paths_reject_absolute_and_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = root / "source"; source.write_text("x")
            with self.assertRaisesRegex(LINEAGE.LineageError, "package-root relative"):
                LINEAGE.safe_file(root, str(source), "legacy absolute")
            with self.assertRaisesRegex(LINEAGE.LineageError, "package-root relative"):
                LINEAGE.safe_file(root, "../source", "escape")

    def test_minimum_atom_mapping_must_preserve_all_orders(self) -> None:
        review = {
            "schema": LINEAGE.REVIEW_SCHEMA, "lineage_id": "lineage_synthetic", "minimum_id": "minimum_synthetic", "state_id": "state_synthetic",
            "workflow_settings": {"temperature_k": 298.15, "standard_state": "1M", "expected_stages": 3},
            "stable_atom_ids": ["atom_o", "atom_h1", "atom_h2"],
            "atom_mapping": [
                {"atom_id": "atom_o", "candidate_index": 1, "input_index": 1, "result_index": 1, "element": "O"},
                {"atom_id": "atom_h1", "candidate_index": 2, "input_index": 3, "result_index": 2, "element": "H"},
                {"atom_id": "atom_h2", "candidate_index": 3, "input_index": 2, "result_index": 3, "element": "H"},
            ],
            "structure_review": {"identity_label": "synthetic water", "formula": "H2O", "connectivity": [], "stereochemistry": [], "connectivity_reviewed": True, "stereochemistry_reviewed": True},
            "decision": "accepted", "explicit_human_review": True, "reviewer": "synthetic reviewer",
            "rationale": "Synthetic mapping regression.", "reviewed_at": "2026-07-19T12:00:00+08:00",
        }
        with self.assertRaisesRegex(LINEAGE.LineageError, "input_index mapping"):
            LINEAGE.normalize_review(review)

    def test_sanitized_84_vs_36_endpoint_mismatch_is_never_qst2_compatible(self) -> None:
        fixture = json.loads((ROOT / "tests/fixtures/scientific_closure_lineage/endpoint_count_mismatch.synthetic.json").read_text())
        reactant = {"charge": 0, "multiplicity": 1, "atoms": [{"element": "C"}] * fixture["reactant"]["atom_count"]}
        product = {"charge": 0, "multiplicity": 1, "atoms": [{"element": "C"}] * fixture["product"]["atom_count"]}
        report = TS.validate_input_family("qst2", {"reactant": reactant, "product": product}, list(range(1, 85)))
        self.assertFalse(report["valid"])
        self.assertIn("product: atom count differs", report["diagnostics"])

    def test_path_acceptance_v2_replays_mechanism_state_direction_and_atom_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            family = {"schema": TS.SCHEMA_V2, "pilot": False, "mechanism_edge_id": "edge1"}
            family_path = root / "family.json"; family_path.write_text(json.dumps(family))
            result = {"schema": TS.TS_RESULT_SCHEMA_V2, "execution": {"family": {"sha256": TS.sha256(family_path)}}, "normal_termination_count": 1, "error_termination_count": 0, "frequency_count": 1, "raw_imaginary_frequency_count": 1, "stationary_point_found": True, "optimization_completed": True, "frequency_parse_complete": True, "expected_frequency_count": 1, "atom_count": 1, "final_coordinates": [{}], "modes": [{"displacements": [{}]}], "first_order_saddle_candidate": True, "mode_review_status": "pending"}
            result_path = root / "result.json"; result_path.write_text(json.dumps(result))
            review = {"schema": "gaussian-ts-mode-review/1", "ts_result_sha256": TS.sha256(result_path)}
            review_path = root / "mode.json"; review_path.write_text(json.dumps(review))
            decision = {"schema": "gaussian-ts-mode-decision/1", "decision": "accepted", "confirmed": True, "ts_result_sha256": TS.sha256(result_path), "mode_review_sha256": TS.sha256(review_path)}
            decision_path = root / "decision.json"; decision_path.write_text(json.dumps(decision))
            mechanism = {"study_id": "study", "states": [{"state_id": "A", "atoms": [{"atom_id": "a1"}, {"atom_id": "a2"}]}, {"state_id": "B", "atoms": [{"atom_id": "b1"}, {"atom_id": "b2"}]}], "edges": [{"edge_id": "edge1", "from_state_id": "A", "to_state_id": "B", "atom_mapping": [{"from_atom_id": "a1", "to_atom_id": "b2"}, {"from_atom_id": "a2", "to_atom_id": "b1"}]}]}
            mechanism_path = root / "mechanism.json"; mechanism_path.write_text(json.dumps(mechanism))
            for name in ("forward", "reverse"):
                (root / f"{name}.json").write_text("{}")
            forward = {"direction": "forward", "chemical_side": "reactant", "charge": 0, "multiplicity": 1, "stable_atom_ids": ["a1", "a2"], "structure_identity": {"state_id": "A", "formula": "H2"}, "endpoint_coordinates": {"records": [{"element": "H"}, {"element": "H"}]}}
            reverse = {"direction": "reverse", "chemical_side": "product", "charge": 0, "multiplicity": 1, "stable_atom_ids": ["b2", "b1"], "structure_identity": {"state_id": "B", "formula": "H2"}, "endpoint_coordinates": {"records": [{"element": "H"}, {"element": "H"}]}}
            binding = {"study_id": "study", "edge_id": "edge1", "from_state_id": "A", "to_state_id": "B", "atom_mapping": mechanism["edges"][0]["atom_mapping"], "direction_mapping": {"forward": {"chemical_side": "reactant", "state_id": "A"}, "reverse": {"chemical_side": "product", "state_id": "B"}}}
            artifact = {"schema": TS.PATH_ACCEPTANCE_SCHEMA_V2, "edge_id": "edge1", "mechanism_network": TS._closure_local_ref(mechanism_path, root, "mechanism"), "mechanism_binding": binding, "family": TS._closure_local_ref(family_path, root, "family"), "ts_result": TS._closure_local_ref(result_path, root, "result"), "mode_review": TS._closure_local_ref(review_path, root, "review"), "mode_decision": TS._closure_local_ref(decision_path, root, "decision"), "endpoint_reviews": {"forward": TS._closure_local_ref(root / "forward.json", root, "forward"), "reverse": TS._closure_local_ref(root / "reverse.json", root, "reverse")}, "accepted": True, "limitations": ["offline fixture"], "validator": TS.PARSER_ID, "calculation_ready": False, "no_submission_authorization": True}
            artifact["payload_sha256"] = TS._payload_sha256(artifact); path = root / "path.json"; path.write_text(json.dumps(artifact))
            owner = SimpleNamespace(validate=lambda _: None)
            def endpoint_owner(candidate: Path):
                return forward if candidate.name == "forward.json" else reverse
            with mock.patch.object(TS, "_load_mechanism_network_owner", return_value=owner), mock.patch.object(TS, "_revalidate_family_scientific_binding", return_value={}), mock.patch.object(TS, "require_accepted_ts_result_v2", return_value=result), mock.patch.object(TS, "validate_mode_review_geometry"), mock.patch.object(TS, "validate_endpoint_structure_review_artifact", side_effect=endpoint_owner):
                TS.validate_path_acceptance_v2_artifact(path)
                forward["structure_identity"]["state_id"] = "B"; reverse["structure_identity"]["state_id"] = "A"
                with self.assertRaisesRegex(ValueError, "swapped, stale"):
                    TS.validate_path_acceptance_v2_artifact(path)
                forward["structure_identity"]["state_id"] = "A"; reverse["structure_identity"]["state_id"] = "B"; reverse["stable_atom_ids"] = ["b1", "b2"]
                with self.assertRaisesRegex(ValueError, "stable atom map"):
                    TS.validate_path_acceptance_v2_artifact(path)


if __name__ == "__main__":
    unittest.main()
