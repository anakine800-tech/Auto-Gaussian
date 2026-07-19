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
MATURITY_V2 = module("closure_maturity_v2_consumer_test", ROOT / "skills/auto-g16-reaction-workflow/scripts/scientific_maturity_v2.py")
OPEN_SHELL_RECEIPT = module("closure_open_shell_receipt_fixture", ROOT / "tests/test_open_shell_input_receipt_bridge.py")
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


def atomic_minimum_log() -> str:
    return (
        " Gaussian 16, Revision C.01\n SCF Done: E(RHF) = -2.0 A.U.\n"
        " Optimization completed.\n Stationary point found.\n Standard orientation:\n"
        " ----------------------------------------\n header\n ----------------------------------------\n"
        " 1 2 0 0.000000 0.000000 0.000000\n ----------------------------------------\n"
        " Normal termination of Gaussian\n"
    )


def ts_execution_sources(root: Path, log_path: Path) -> dict[str, Path]:
    route = "#p hf/sto-3g opt=(ts,calcfc) freq"
    input_path = root / "water-ts.gjf"; input_path.write_text(f"%chk=water-ts.chk\n{route}\n\nTS\n\n0 1\nO 0 0 0\nH .95 0 0\nH -.25 .92 0\n\n")
    audit = TS.validate_input_family("single_guess", {"ts": TS.parse_cartesian_input(input_path)}, [1, 2, 3])
    protocol = {"project_prefix": "waterts", "routes": {"ts_freq": route}}
    family_path = root / "family.json"; family_path.write_text(json.dumps({"schema": TS.SCHEMA_V2, "pilot": False, "mechanism_edge_id": "edge_water", "project_prefix": "waterts", "input_audit": audit, "protocol": protocol}))
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
    checkpoint = root / "water-ts.chk"; checkpoint.write_bytes(b"synthetic TS checkpoint")
    digest = TS.sha256(log_path); checkpoint_digest = TS.sha256(checkpoint)
    snapshot = {
        "schema": "gaussian-fetch-snapshot/1", "project": project, "job_id": job_id,
        "input_stem": input_path.stem, "input_sha256": TS.sha256(input_path), "snapshot_complete": True,
        "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "per_hop_sha256_verified": True,
        "exact_log": log_path.name,
        "artifacts": {log_path.name: {"sha256": digest, "size": log_path.stat().st_size}, checkpoint.name: {"sha256": checkpoint_digest, "size": checkpoint.stat().st_size}},
        "per_hop": {log_path.name: {"server_sha256": digest, "rtwin_sha256": digest, "mac_sha256": digest, "size": log_path.stat().st_size}, checkpoint.name: {"server_sha256": checkpoint_digest, "rtwin_sha256": checkpoint_digest, "mac_sha256": checkpoint_digest, "size": checkpoint.stat().st_size}},
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
    def test_gaussian_log_file_api_is_streaming_and_text_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); text = water_log(); log_path = root / "small.log"; log_path.write_text(text)
            expected = LOG.analyze_log_text(text)
            requests: list[int] = []; original_read = LOG.os.read
            def observed(fd: int, size: int) -> bytes:
                requests.append(size); return original_read(fd, size)
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("file API used read_text")), mock.patch.object(LOG.os, "read", side_effect=observed):
                actual = LOG.analyze_log_file(log_path)
            actual.pop("log")
            self.assertEqual(actual, expected)
            self.assertLessEqual(max(requests), LOG.FILE_READ_CHUNK_SIZE)

            sparse = root / "sparse-large.log"
            with sparse.open("w", encoding="utf-8") as handle:
                handle.write("filler line\n" * 400_000)
                handle.write(text)
            requests.clear()
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("file API used read_text")), mock.patch.object(LOG.os, "read", side_effect=observed):
                large = LOG.analyze_workflow_log_file(sparse, None, temperature_k=298.15, standard_state="1M", expected_stages=3)
            expected_workflow = LOG.analyze_workflow_log_text("filler line\n" * 2 + text, temperature_k=298.15, standard_state="1M", expected_stages=3)
            large.pop("log")
            self.assertEqual(large, expected_workflow)
            self.assertLessEqual(max(requests), LOG.FILE_READ_CHUNK_SIZE)

    def test_new_contract_schemas_use_supported_offline_subset(self) -> None:
        names = (
            "endpoint-structure-review.schema.json", "endpoint-structure-review-v2.schema.json", "minimum-lineage-handoff.schema.json",
            "minimum-lineage-handoff-v2.schema.json",
            "ts-irc-path-acceptance-v2.schema.json", "ts-freq-result-v2.schema.json",
            "fragment-endpoint-validation-v2.schema.json",
            "checkpoint-geometry-audit-v2.schema.json",
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

    def test_minimum_lineage_v2_real_build_publish_owner_and_maturity_consumer(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp).resolve()
            chain = OPEN_SHELL_RECEIPT.OpenShellInputReceiptBridgeTests(
                "test_open_shell_minimum_receipt_replays_all_owners_and_closed_schema"
            ).build_receipt(root)
            input_path = chain["input_path"]; approval_path = chain["receipt_path"]
            atoms = [(6, "C", 0.0, 0.0, 0.0), (1, "H", 1.08, 0.0, 0.0), (1, "H", -0.54, 0.935307, 0.0), (1, "H", -0.54, -0.935307, 0.0)]
            rows = "\n".join(f" {index} {number} 0 {x:.6f} {y:.6f} {z:.6f}" for index, (number, _element, x, y, z) in enumerate(atoms, 1))
            log_text = (" SCF Done: E(UB3LYP) = -39.000000 A.U.\n Optimization completed.\n Stationary point found.\n Standard orientation:\n ----------------------------------------\n header\n ----------------------------------------\n" + rows + "\n ----------------------------------------\n Frequencies -- 100.0 200.0 300.0\n Frequencies -- 400.0 500.0 600.0\n Thermal correction to Gibbs Free Energy= 0.010000\n Normal termination of Gaussian\n")
            log_path = root / "ch3.log"; log_path.write_text(log_text)
            result = LOG.analyze_workflow_log_text(log_text, temperature_k=298.15, standard_state="1M", expected_stages=1)
            result_path = root / "ch3-result.json"; result_path.write_text(json.dumps(result))
            checkpoint = root / "ch3.chk"; checkpoint.write_bytes(b"reviewed ch3 minimum checkpoint")
            xyz = root / "ch3.xyz"; xyz.write_text("4\naccepted ch3 minimum\n" + "\n".join(f"{element} {x} {y} {z}" for _number, element, x, y, z in atoms) + "\n")
            ensemble = root / "ensemble.json"; ensemble.write_text("{}\n")
            selection = {"schema": LINEAGE.SELECTION_SCHEMA, "candidate_only": True, "calculation_ready": False, "no_submission_authorization": True, "selection_is_not_authorization": True, "workflow_states": {"human_selected": True, "input_draft_generated": True, "exact_input_approved": False, "submission_authorized": False, "result_accepted": False}, "selection": {"ensemble": ensemble.name, "ensemble_sha256": LINEAGE.file_sha256(ensemble), "ensemble_size_bytes": ensemble.stat().st_size}, "gaussian_input": input_path.name, "gaussian_input_sha256": LINEAGE.file_sha256(input_path), "gaussian_input_size_bytes": input_path.stat().st_size, "xyz_coordinates": xyz.name, "xyz_sha256": LINEAGE.file_sha256(xyz), "xyz_size_bytes": xyz.stat().st_size, "candidate_atom_elements": [item[1] for item in atoms], "formula": "CH3"}
            selection_path = root / "conformer-selection-receipt.json"; selection_path.write_text(json.dumps(selection))
            project, job_id, attempt_id = "ch3minimum", "31.master", "qsub-attempt-ch3-minimum"
            inspection = {"schema": "gaussian-job-inspection/2", "project": project, "job_id": job_id, "state": "completed", "collected_at": "2026-07-19T12:00:00Z", "source": "single_remote_read_only_snapshot", "freshness": "fresh", "transport_classification": "success", "transport_returncode": 0, "termination_counts_known": True, "evidence_conflict": False, "process_alive": False, "log_size": log_path.stat().st_size, "full_normal_termination_count": 1, "full_error_termination_count": 0}
            inspection["evidence_sha256"] = LINEAGE.transport_digest(inspection)
            receipt = {"schema": "gaussian-terminal-inspection-receipt/1", "project": project, "job_id": job_id, "input_stem": input_path.stem, "input_sha256": LINEAGE.file_sha256(input_path), "attempt_id": attempt_id, "terminal_state": "completed", "collected_at": inspection["collected_at"], "inspection_evidence_sha256": inspection["evidence_sha256"], "inspection": inspection, "scientific_acceptance": False}
            receipt["receipt_sha256"] = LINEAGE.transport_digest(receipt); receipt_path = root / "terminal-inspection.json"; receipt_path.write_text(json.dumps(receipt))
            artifacts = {source.name: {"sha256": LINEAGE.file_sha256(source), "size": source.stat().st_size} for source in (log_path, result_path, checkpoint)}
            per_hop = {name: {"server_sha256": value["sha256"], "rtwin_sha256": value["sha256"], "mac_sha256": value["sha256"], "size": value["size"]} for name, value in artifacts.items()}
            snapshot = {"schema": "gaussian-fetch-snapshot/1", "project": project, "job_id": job_id, "input_sha256": LINEAGE.file_sha256(input_path), "snapshot_complete": True, "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "per_hop_sha256_verified": True, "artifacts": artifacts, "per_hop": per_hop}
            snapshot["payload_sha256"] = LINEAGE.transport_digest(snapshot); snapshot_path = root / "transfer.json"; snapshot_path.write_text(json.dumps(snapshot))
            job = {"schema": "gaussian-rtwin-pbs/1", "project": project, "job_id": job_id, "status": "completed", "results_fetched": True, "input_sha256": LINEAGE.file_sha256(input_path), "execution_batch": {"attempt_id": attempt_id}, "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "fetch_snapshot_sha256": LINEAGE.file_sha256(snapshot_path), "fetch_snapshot_size": snapshot_path.stat().st_size}
            job_path = root / "job.json"; job_path.write_text(json.dumps(job))
            review = {"schema": LINEAGE.REVIEW_SCHEMA, "lineage_id": "ch3_minimum_lineage", "minimum_id": "minimum_ch3", "state_id": "state_ch3", "workflow_settings": {"temperature_k": 298.15, "standard_state": "1M", "expected_stages": 1}, "stable_atom_ids": ["c", "h1", "h2", "h3"], "atom_mapping": [{"atom_id": atom_id, "candidate_index": index, "input_index": index, "result_index": index, "element": element} for index, (atom_id, element) in enumerate(zip(["c", "h1", "h2", "h3"], ["C", "H", "H", "H"]), 1)], "structure_review": {"identity_label": "reviewed CH3 minimum", "formula": "CH3", "connectivity": [], "stereochemistry": [], "connectivity_reviewed": True, "stereochemistry_reviewed": True}, "decision": "accepted", "explicit_human_review": True, "reviewer": "offline fixture reviewer", "rationale": "Exact owner-chain integration fixture.", "reviewed_at": "2026-07-19T12:00:00Z"}
            review_path = root / "lineage-review.json"; review_path.write_text(json.dumps(review))
            output = root / "minimum-lineage.json"
            built = LINEAGE.build(root, {"selection": selection_path, "input_approval": approval_path, "input": input_path, "job": job_path, "result": result_path, "raw_log": log_path, "checkpoint": checkpoint, "optimized_coordinates": xyz, "terminal_inspection_receipt": receipt_path, "fetch_snapshot": snapshot_path}, review_path, output, source_kind="conformer_selection")
            self.assertEqual(LINEAGE.validate_artifact(output), built)
            binding = {"path": output.name, "sha256": LINEAGE.file_sha256(output), "size_bytes": output.stat().st_size, "schema": built["schema"], "payload_sha256": built["payload_sha256"]}
            consumed = MATURITY_V2.consume_minimum_lineage_v2(binding, root / "maturity-review.json", minimum_id="minimum_ch3", state_id="state_ch3", formula="CH3", formal_charge=0, multiplicity=2, stable_atom_ids=["c", "h1", "h2", "h3"])
            self.assertEqual(consumed["payload_sha256"], built["payload_sha256"])
            with self.assertRaisesRegex(MATURITY_V2.EvidenceOverlayError, "another mechanism state"):
                MATURITY_V2.consume_minimum_lineage_v2(binding, root / "maturity-review.json", minimum_id="minimum_ch3", state_id="stale_state", formula="CH3", formal_charge=0, multiplicity=2, stable_atom_ids=["c", "h1", "h2", "h3"])

            original_snapshot = json.loads(snapshot_path.read_text()); original_job = json.loads(job_path.read_text())
            def replay_with_snapshot_mutation(mutator, message: str) -> None:
                changed_snapshot = json.loads(json.dumps(original_snapshot)); mutator(changed_snapshot)
                changed_snapshot["payload_sha256"] = LINEAGE.transport_digest({key: value for key, value in changed_snapshot.items() if key != "payload_sha256"})
                snapshot_path.write_text(json.dumps(changed_snapshot))
                changed_job = json.loads(json.dumps(original_job)); changed_job["fetch_snapshot_sha256"] = LINEAGE.file_sha256(snapshot_path); changed_job["fetch_snapshot_size"] = snapshot_path.stat().st_size
                job_path.write_text(json.dumps(changed_job))
                replay = json.loads(json.dumps(built)); replay["sources"]["fetch_snapshot"] = LINEAGE.reference(snapshot_path, root, json_document=changed_snapshot); replay["sources"]["job"] = LINEAGE.reference(job_path, root, json_document=changed_job); replay["payload_sha256"] = LINEAGE.payload_sha256(replay)
                with self.assertRaisesRegex(LINEAGE.LineageError, message):
                    LINEAGE.replay_minimum_sources(root, replay)
                snapshot_path.write_text(json.dumps(original_snapshot)); job_path.write_text(json.dumps(original_job))
            replay_with_snapshot_mutation(lambda value: value.__setitem__("per_hop_sha256_verified", False), "incomplete or invalid")
            replay_with_snapshot_mutation(lambda value: value.pop("per_hop"), "per-hop")
            replay_with_snapshot_mutation(lambda value: value["per_hop"][log_path.name].__setitem__("rtwin_sha256", "f" * 64), "per-hop")

            original_receipt = json.loads(receipt_path.read_text())
            changed_receipt = json.loads(json.dumps(original_receipt)); changed_receipt["inspection"]["state"] = "failed"; changed_receipt["inspection"]["evidence_sha256"] = LINEAGE.transport_digest({key: value for key, value in changed_receipt["inspection"].items() if key != "evidence_sha256"}); changed_receipt["inspection_evidence_sha256"] = changed_receipt["inspection"]["evidence_sha256"]; changed_receipt["receipt_sha256"] = LINEAGE.transport_digest({key: value for key, value in changed_receipt.items() if key != "receipt_sha256"}); receipt_path.write_text(json.dumps(changed_receipt))
            changed_snapshot = json.loads(json.dumps(original_snapshot)); changed_snapshot["terminal_inspection_receipt_sha256"] = changed_receipt["receipt_sha256"]; changed_snapshot["payload_sha256"] = LINEAGE.transport_digest({key: value for key, value in changed_snapshot.items() if key != "payload_sha256"}); snapshot_path.write_text(json.dumps(changed_snapshot))
            changed_job = json.loads(json.dumps(original_job)); changed_job["terminal_inspection_receipt_sha256"] = changed_receipt["receipt_sha256"]; changed_job["fetch_snapshot_sha256"] = LINEAGE.file_sha256(snapshot_path); changed_job["fetch_snapshot_size"] = snapshot_path.stat().st_size; job_path.write_text(json.dumps(changed_job))
            replay = json.loads(json.dumps(built)); replay["sources"]["terminal_inspection_receipt"] = LINEAGE.reference(receipt_path, root, json_document=changed_receipt); replay["sources"]["fetch_snapshot"] = LINEAGE.reference(snapshot_path, root, json_document=changed_snapshot); replay["sources"]["job"] = LINEAGE.reference(job_path, root, json_document=changed_job); replay["payload_sha256"] = LINEAGE.payload_sha256(replay)
            with self.assertRaisesRegex(LINEAGE.LineageError, "project/job/state/source/returncode"):
                LINEAGE.replay_minimum_sources(root, replay)

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

    def test_ts_result_v2_rejects_resealed_cross_family_input_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); log_path = root / "water-ts.log"
            log_path.write_text(water_log(" Frequencies -- -100.0 200.0 300.0"))
            sources = ts_execution_sources(root, log_path)
            result_path = root / "result.json"
            result = TS.build_ts_result_v2(log_path, result_path, sources)

            other_input = root / "other-water-ts.gjf"
            original_input = sources["input"].read_text()
            other_input.write_text(original_input.replace("H .95 0 0", "H 1.95 0 0"))
            other_audit = TS.validate_input_family(
                "single_guess", {"ts": TS.parse_cartesian_input(other_input)}, [1, 2, 3]
            )
            family = json.loads(sources["family"].read_text())
            family["input_audit"] = other_audit
            other_family = root / "other-family.json"; other_family.write_text(json.dumps(family))
            result["execution"]["family"] = TS._closure_local_ref(other_family, root, "other family")
            result["payload_sha256"] = TS._payload_sha256(result)
            result_path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "exact input bytes, coordinates"):
                TS.validate_ts_result_v2(result, result_path)

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

    def test_ts_result_v2_checkpoint_gate_replays_exact_input_log_and_fetched_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); log_path = root / "water-ts.log"
            log_path.write_text(water_log(" Frequencies -- -100.0 200.0 300.0").replace(" SCF Done:", " Charge = 0 Multiplicity = 1\n SCF Done:"))
            sources = ts_execution_sources(root, log_path); checkpoint = root / "water-ts.chk"
            result_path = root / "result.json"; result = TS.build_ts_result_v2(log_path, result_path, sources)
            mode_dir = root / "mode"; TS.create_mode_review(result, [(1, 2)], mode_dir, 0.1, TS.sha256(result_path))
            review_path = mode_dir / "mode_review.json"; decision_path = root / "decision.json"
            TS.record_mode_decision(review_path, "accepted", decision_path)
            audit = TS.audit_checkpoint_provenance(sources["input"], log_path, result_path, checkpoint, review_path, decision_path)
            self.assertEqual(audit["schema"], "gaussian-checkpoint-geometry-audit/2")
            self.assertTrue(audit["checks"]["checkpoint_is_exact_hash_verified_fetch_artifact"])
            audit_path = root / "checkpoint-audit.json"; audit_path.write_text(json.dumps(audit))
            self.assertEqual(TS.validate_checkpoint_audit_artifact(audit_path), audit)
            schema = json.loads((ROOT / "contracts/reaction-workflow/checkpoint-geometry-audit-v2.schema.json").read_text())
            SCHEMA_VALIDATOR._validate_schema_instance(audit, schema, schema)
            manifest = TS.build_allcheck_irc_input(audit_path, checkpoint, root / "irc-forward.gjf", "#p hf/sto-3g irc=(forward,rcfc) geom=allcheck guess=read", "forward", "12GB", 8)
            self.assertEqual(manifest["checkpoint_sha256"], TS.sha256(checkpoint))
            cli_audit = root / "checkpoint-audit-cli.json"
            cli = ["python3", str(ROOT / "skills/auto-g16-ts-irc/scripts/ts_irc.py")]
            completed = subprocess.run(cli + ["audit-checkpoint", "--ts-input", str(sources["input"]), "--ts-log", str(log_path), "--ts-result", str(result_path), "--checkpoint", str(checkpoint), "--mode-review", str(review_path), "--mode-decision", str(decision_path), "--output", str(cli_audit)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertEqual(TS.validate_checkpoint_audit_artifact(cli_audit)["schema"], "gaussian-checkpoint-geometry-audit/2")
            cli_irc = root / "irc-reverse-cli.gjf"
            completed = subprocess.run(cli + ["build-allcheck-irc", "--checkpoint-audit", str(cli_audit), "--checkpoint", str(checkpoint), "--output", str(cli_irc), "--route", "#p hf/sto-3g irc=(reverse,rcfc) geom=allcheck guess=read", "--direction", "reverse", "--memory", "12GB", "--nprocshared", "8"], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertTrue(cli_irc.is_file())

            wrong_log = root / "copy.log"; wrong_log.write_bytes(log_path.read_bytes())
            with self.assertRaisesRegex(ValueError, "source_log is not the supplied"):
                TS.audit_checkpoint_provenance(sources["input"], wrong_log, result_path, checkpoint, review_path, decision_path)
            wrong_input = root / "copy.gjf"; wrong_input.write_bytes(sources["input"].read_bytes())
            with self.assertRaisesRegex(ValueError, "execution input is not the supplied"):
                TS.audit_checkpoint_provenance(wrong_input, log_path, result_path, checkpoint, review_path, decision_path)
            forged = json.loads(json.dumps(audit))
            forged["sources"]["ts_input"] = TS._closure_local_ref(wrong_input, root, "forged checkpoint audit input")
            forged["payload_sha256"] = TS._payload_sha256(forged)
            forged_path = root / "forged-checkpoint-audit.json"; forged_path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, "execution input is not the supplied"):
                TS.build_allcheck_irc_input(forged_path, checkpoint, root / "forged-irc.gjf", "#p hf/sto-3g irc=(forward,rcfc) geom=allcheck guess=read", "forward", "12GB", 8)
            original_checkpoint = checkpoint.read_bytes(); checkpoint.write_bytes(b"same basename, different checkpoint")
            with self.assertRaisesRegex(ValueError, "hash-verified fetch artifact"):
                TS.audit_checkpoint_provenance(sources["input"], log_path, result_path, checkpoint, review_path, decision_path)
            checkpoint.write_bytes(original_checkpoint)

            snapshot_path = sources["fetch_snapshot"]; snapshot = json.loads(snapshot_path.read_text())
            snapshot["per_hop"][checkpoint.name]["server_sha256"] = "f" * 64
            snapshot["payload_sha256"] = TS._transport_digest({key: value for key, value in snapshot.items() if key != "payload_sha256"})
            snapshot_path.write_text(json.dumps(snapshot))
            job_path = sources["job"]; job = json.loads(job_path.read_text()); job["fetch_snapshot_sha256"] = TS.sha256(snapshot_path); job["fetch_snapshot_size"] = snapshot_path.stat().st_size; job_path.write_text(json.dumps(job))
            result = json.loads(result_path.read_text())
            for key, source in (("job", job_path), ("fetch_snapshot", snapshot_path)):
                result["execution"][key]["sha256"] = TS.sha256(source); result["execution"][key]["size_bytes"] = source.stat().st_size
            result["payload_sha256"] = TS._payload_sha256(result); result_path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "hash-verified fetch artifact"):
                TS.audit_checkpoint_provenance(sources["input"], log_path, result_path, checkpoint, review_path, decision_path)

    def test_fragment_v2_replays_each_full_log_and_rejects_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            projects = ("frag_a", "frag_b", "frag_atom")
            plan = {
                "schema": "gaussian-irc-fragment-endpoint-plan/1", "status": "planned_not_submitted",
                "chemical_side": "product", "fragments": [],
            }
            results: dict[str, Path] = {}; jobs: dict[str, Path] = {}; inputs: dict[str, Path] = {}
            logs: dict[str, Path] = {}; checkpoints: dict[str, Path] = {}; receipts: dict[str, Path] = {}; snapshots: dict[str, Path] = {}
            for index, project in enumerate(projects, start=1):
                project_dir = root / project; project_dir.mkdir()
                atomic = project == "frag_atom"
                input_path = project_dir / f"{project}.gjf"; input_path.write_text("#p hf/sto-3g opt freq\n\nfragment\n\n0 1\n" + ("He 0 0 0\n\n" if atomic else "O 0 0 0\nH .95 0 0\nH -.25 .92 0\n\n"))
                input_sha = TS.sha256(input_path)
                plan["fragments"].append({
                    "project": project, "identity": f"synthetic fragment {index}", "formula": "He" if atomic else "H2O",
                    "atom_count": 1 if atomic else 3, "element_order": ["He"] if atomic else ["O", "H", "H"], "input_sha256": input_sha,
                })
                log_path = project_dir / f"{project}.log"; log_path.write_text(atomic_minimum_log() if atomic else water_log())
                result_path = project_dir / f"{project}.result.json"; result_path.write_text(json.dumps(LOG.analyze_log_text(log_path.read_text())))
                checkpoint = project_dir / f"{project}.chk"; checkpoint.write_bytes(f"synthetic {project}".encode())
                job_id, attempt_id = f"{index}.master", f"qsub-attempt-{project}"
                text = log_path.read_text(); inspection = {"schema": "gaussian-job-inspection/2", "project": project, "job_id": job_id, "state": "completed", "collected_at": "2026-07-19T12:00:00Z", "source": "single_remote_read_only_snapshot", "freshness": "fresh", "transport_classification": "success", "transport_returncode": 0, "termination_counts_known": True, "evidence_conflict": False, "process_alive": False, "log_size": log_path.stat().st_size, "full_normal_termination_count": text.count("Normal termination of Gaussian"), "full_error_termination_count": 0}
                inspection["evidence_sha256"] = TS._transport_digest(inspection)
                receipt = {"schema": "gaussian-terminal-inspection-receipt/1", "project": project, "job_id": job_id, "input_stem": input_path.stem, "input_sha256": input_sha, "attempt_id": attempt_id, "terminal_state": "completed", "collected_at": inspection["collected_at"], "inspection_evidence_sha256": inspection["evidence_sha256"], "inspection": inspection, "scientific_acceptance": False}
                receipt["receipt_sha256"] = TS._transport_digest(receipt); receipt_path = project_dir / "terminal-inspection.json"; receipt_path.write_text(json.dumps(receipt))
                artifacts = {}; per_hop = {}
                for source in (log_path, result_path, checkpoint):
                    digest = TS.sha256(source); artifacts[source.name] = {"sha256": digest, "size": source.stat().st_size}; per_hop[source.name] = {"server_sha256": digest, "rtwin_sha256": digest, "mac_sha256": digest, "size": source.stat().st_size}
                snapshot = {"schema": "gaussian-fetch-snapshot/1", "project": project, "job_id": job_id, "input_stem": input_path.stem, "input_sha256": input_sha, "snapshot_complete": True, "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "per_hop_sha256_verified": True, "exact_log": log_path.name, "artifacts": artifacts, "per_hop": per_hop}
                snapshot["payload_sha256"] = TS._transport_digest(snapshot); snapshot_path = project_dir / "transfer.json"; snapshot_path.write_text(json.dumps(snapshot))
                job_path = project_dir / f"{project}.job.json"; job_path.write_text(json.dumps({"schema": "gaussian-rtwin-pbs/1", "project": project, "job_id": job_id, "status": "completed", "results_fetched": True, "input_sha256": input_sha, "execution_batch": {"attempt_id": attempt_id}, "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "fetch_snapshot_sha256": TS.sha256(snapshot_path), "fetch_snapshot_size": snapshot_path.stat().st_size}))
                results[project] = result_path; jobs[project] = job_path; inputs[project] = input_path; logs[project] = log_path; checkpoints[project] = checkpoint; receipts[project] = receipt_path; snapshots[project] = snapshot_path
            plan_path = root / "plan.json"; plan_path.write_text(json.dumps(plan))
            artifact = TS.audit_fragment_endpoint_results_v2(plan_path, results, jobs, inputs, logs, checkpoints, receipts, snapshots, root / "accepted.json")
            self.assertEqual(artifact["validator"], TS.PARSER_ID)
            atom = next(item for item in artifact["fragments"] if item["project"] == "frag_atom")
            self.assertEqual((atom["frequency_count"], atom["expected_frequency_count"], atom["lowest_frequency_cm-1"]), (0, 0, None))
            self.assertTrue(all(item["frequency_count"] == item["expected_frequency_count"] == 3 for item in artifact["fragments"] if item["project"] != "frag_atom"))
            schema = json.loads((ROOT / "contracts/reaction-workflow/fragment-endpoint-validation-v2.schema.json").read_text())
            SCHEMA_VALIDATOR._validate_schema_instance(artifact, schema, schema)
            TS.validate_fragment_endpoint_results_v2(root / "accepted.json")
            cli_output = root / "accepted-cli.json"; command = ["python3", str(ROOT / "skills/auto-g16-ts-irc/scripts/ts_irc.py"), "audit-fragment-endpoints-v2", "--plan", str(plan_path), "--output", str(cli_output)]
            for option, values in (("result", results), ("job", jobs), ("input", inputs), ("log", logs), ("checkpoint", checkpoints), ("terminal-inspection-receipt", receipts), ("fetch-snapshot", snapshots)):
                for project in projects:
                    command.extend(["--" + option, f"{project}={values[project]}"])
            completed = subprocess.run(command, capture_output=True, text=True); self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            TS.validate_fragment_endpoint_results_v2(cli_output)
            receipt_original = receipts["frag_a"].read_bytes(); crossed = json.loads(receipts["frag_a"].read_text()); crossed["attempt_id"] = "qsub-attempt-other"; crossed["receipt_sha256"] = TS._transport_digest({key: value for key, value in crossed.items() if key != "receipt_sha256"}); receipts["frag_a"].write_text(json.dumps(crossed))
            with self.assertRaisesRegex(ValueError, "exact project/job/attempt/input"):
                TS.audit_fragment_endpoint_results_v2(plan_path, results, jobs, inputs, logs, checkpoints, receipts, snapshots, root / "cross-attempt.json")
            receipts["frag_a"].write_bytes(receipt_original)
            forged_atom = json.loads(json.dumps(artifact)); forged_record = next(item for item in forged_atom["fragments"] if item["project"] == "frag_atom"); forged_record["frequency_count"] = 1; forged_record["expected_frequency_count"] = 1; forged_record["lowest_frequency_cm-1"] = 100.0; forged_atom["payload_sha256"] = TS._payload_sha256(forged_atom)
            forged_atom_path = root / "forged-atom.json"; forged_atom_path.write_text(json.dumps(forged_atom))
            with self.assertRaisesRegex(ValueError, "owner replay"):
                TS.validate_fragment_endpoint_results_v2(forged_atom_path)
            forged_lowest = json.loads(json.dumps(artifact)); next(item for item in forged_lowest["fragments"] if item["project"] == "frag_atom")["lowest_frequency_cm-1"] = 0.0; forged_lowest["payload_sha256"] = TS._payload_sha256(forged_lowest)
            forged_lowest_path = root / "forged-atom-lowest.json"; forged_lowest_path.write_text(json.dumps(forged_lowest))
            with self.assertRaisesRegex(ValueError, "owner replay"):
                TS.validate_fragment_endpoint_results_v2(forged_lowest_path)
            forged = json.loads(json.dumps(artifact)); forged["fragments"][0]["minimum_accepted"] = False; forged["payload_sha256"] = TS._payload_sha256(forged)
            forged_path = root / "forged.json"; forged_path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, "owner replay"):
                TS.validate_fragment_endpoint_results_v2(forged_path)

            logs["frag_b"].write_text(water_log(" Frequencies -- 100.0 200.0"))
            with self.assertRaisesRegex(ValueError, "reference changed"):
                TS.validate_fragment_endpoint_results_v2(root / "accepted.json")
            results["frag_b"].write_text(json.dumps(LOG.analyze_log_text(logs["frag_b"].read_text())))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                TS.audit_fragment_endpoint_results_v2(plan_path, results, jobs, inputs, logs, checkpoints, receipts, snapshots, root / "rejected.json")

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
            mechanism = {"schema": "gaussian-reaction-mechanism-network/1", "study_id": "study", "states": [{"state_id": "A", "formal_charge": 0, "multiplicity": 1, "atoms": [{"atom_id": "a1", "element": "H"}, {"atom_id": "a2", "element": "H"}]}, {"state_id": "B", "formal_charge": 0, "multiplicity": 1, "atoms": [{"atom_id": "b1", "element": "H"}, {"atom_id": "b2", "element": "H"}]}], "edges": [{"edge_id": "edge1", "from_state_id": "A", "to_state_id": "B", "atom_mapping": [{"from_atom_id": "a1", "to_atom_id": "b2"}, {"from_atom_id": "a2", "to_atom_id": "b1"}]}]}
            mechanism["payload_sha256"] = TS._payload_sha256(mechanism)
            mechanism_path = root / "mechanism.json"; mechanism_path.write_text(json.dumps(mechanism))
            for name in ("forward", "reverse"):
                (root / f"{name}.json").write_text("{}")
            for name in ("forward", "reverse"):
                (root / f"{name}-audit.json").write_text(json.dumps({
                    "schema": "gaussian-irc-endpoint-audit/2",
                    "ts_checkpoint_sha256": "1" * 64,
                    "checkpoint_audit_sha256": "2" * 64,
                    "irc_plan_sha256": "3" * 64,
                }))
            forward_sources = {"family": {"sha256": TS.sha256(family_path)}, "audit": TS._closure_local_ref(root / "forward-audit.json", root, "forward audit")}
            reverse_sources = {"family": {"sha256": TS.sha256(family_path)}, "audit": TS._closure_local_ref(root / "reverse-audit.json", root, "reverse audit")}
            forward = {"schema": TS.ENDPOINT_REVIEW_SCHEMA_V2, "sources": forward_sources, "direction": "forward", "chemical_side": "reactant", "charge": 0, "multiplicity": 1, "stable_atom_ids": ["a1", "a2"], "structure_identity": {"state_id": "A", "formula": "H2"}, "endpoint_coordinates": {"records": [{"element": "H"}, {"element": "H"}]}}
            reverse = {"schema": TS.ENDPOINT_REVIEW_SCHEMA_V2, "sources": reverse_sources, "direction": "reverse", "chemical_side": "product", "charge": 0, "multiplicity": 1, "stable_atom_ids": ["b2", "b1"], "structure_identity": {"state_id": "B", "formula": "H2"}, "endpoint_coordinates": {"records": [{"element": "H"}, {"element": "H"}]}}
            binding = {"study_id": "study", "edge_id": "edge1", "from_state_id": "A", "to_state_id": "B", "atom_mapping": mechanism["edges"][0]["atom_mapping"], "direction_mapping": {"forward": {"chemical_side": "reactant", "state_id": "A", "formal_charge": 0, "multiplicity": 1, "stable_atoms": [{"atom_id": "a1", "element": "H"}, {"atom_id": "a2", "element": "H"}]}, "reverse": {"chemical_side": "product", "state_id": "B", "formal_charge": 0, "multiplicity": 1, "stable_atoms": [{"atom_id": "b2", "element": "H"}, {"atom_id": "b1", "element": "H"}]}}}
            artifact = {"schema": TS.PATH_ACCEPTANCE_SCHEMA_V2, "edge_id": "edge1", "mechanism_network": TS._closure_json_ref(mechanism_path, root, "mechanism"), "mechanism_binding": binding, "family": TS._closure_local_ref(family_path, root, "family"), "ts_result": TS._closure_local_ref(result_path, root, "result"), "mode_review": TS._closure_local_ref(review_path, root, "review"), "mode_decision": TS._closure_local_ref(decision_path, root, "decision"), "endpoint_reviews": {"forward": TS._closure_local_ref(root / "forward.json", root, "forward"), "reverse": TS._closure_local_ref(root / "reverse.json", root, "reverse")}, "accepted": True, "limitations": ["offline fixture"], "validator": TS.PARSER_ID, "calculation_ready": False, "no_submission_authorization": True}
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
                reverse["stable_atom_ids"] = ["b2", "b1"]; forward["charge"] = 1
                with self.assertRaisesRegex(ValueError, "charge or multiplicity"):
                    TS.validate_path_acceptance_v2_artifact(path)
                forward["charge"] = 0; reverse["multiplicity"] = 3
                with self.assertRaisesRegex(ValueError, "charge or multiplicity"):
                    TS.validate_path_acceptance_v2_artifact(path)
                reverse["multiplicity"] = 1; forward["endpoint_coordinates"]["records"][0]["element"] = "He"; reverse["endpoint_coordinates"]["records"][0]["element"] = "He"
                with self.assertRaisesRegex(ValueError, "element/order"):
                    TS.validate_path_acceptance_v2_artifact(path)
                forward["endpoint_coordinates"]["records"][0]["element"] = "H"; reverse["endpoint_coordinates"]["records"][0]["element"] = "H"
                reverse_audit_path = root / "reverse-audit.json"
                reverse_audit = json.loads(reverse_audit_path.read_text()); reverse_audit["ts_checkpoint_sha256"] = "9" * 64
                reverse_audit_path.write_text(json.dumps(reverse_audit)); reverse["sources"]["audit"] = TS._closure_local_ref(reverse_audit_path, root, "reverse audit")
                with self.assertRaisesRegex(ValueError, "same accepted TS lineage"):
                    TS.validate_path_acceptance_v2_artifact(path)
                reverse_audit["ts_checkpoint_sha256"] = "1" * 64; reverse_audit_path.write_text(json.dumps(reverse_audit)); reverse["sources"]["audit"] = TS._closure_local_ref(reverse_audit_path, root, "reverse audit")
                forward["sources"]["family"]["sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "another TS family"):
                    TS.validate_path_acceptance_v2_artifact(path)


if __name__ == "__main__":
    unittest.main()
