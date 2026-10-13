#!/usr/bin/env python3
"""Real-file, zero-network integration for the protected QST3 successor."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import test_gaussian_ts_irc as TS_SUPPORT
from tests import test_live_approval_effect_time_replay as REPLAY_SUPPORT
from tests import test_protocol_selection as PROTOCOL_SUPPORT
from tests import test_scientific_maturity_v2 as MATURITY_SUPPORT
from tests.test_protected_qst3_adapter import (
    ADAPTER,
    LEGACY,
    MATURITY,
    TS,
    ROOT,
    module,
    write,
)


PBS = module(
    "protected_qst3_real_chain_pbs",
    ROOT / "skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py",
)
LINEAGE = module(
    "protected_qst3_real_chain_lineage",
    ROOT
    / "skills/auto-g16-reaction-workflow/scripts/scientific_closure_lineage.py",
)
LOG = module(
    "protected_qst3_real_chain_log",
    ROOT / "skills/auto-g16-rtwin-pbs/scripts/gaussian_log.py",
)
REPLAY = REPLAY_SUPPORT.REPLAY
PROTOCOL = PROTOCOL_SUPPORT.PROTOCOL


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def formula(elements: list[str]) -> str:
    counts: dict[str, int] = {}
    order: list[str] = []
    for element in elements:
        if element not in counts:
            counts[element] = 0
            order.append(element)
        counts[element] += 1
    return "".join(
        element + (str(counts[element]) if counts[element] != 1 else "")
        for element in order
    )


def protocol_files(
    root: Path,
    *,
    stem: str,
    task_types: list[str],
    elements: list[str],
    charge: int,
    multiplicity: int,
    tier: str,
) -> tuple[Path, Path, dict, dict, dict]:
    request = PROTOCOL_SUPPORT.request_fixture()
    unique_elements = list(dict.fromkeys(elements))
    request.update({
        "request_id": f"{stem.replace('-', '_')}_request",
        "goal": "Synthetic offline identity-chain regression only.",
        "claim_scope": "No scientific or live claim.",
        "task_types": task_types,
        "structure": {
            "sha256": hashlib.sha256((stem + "-structure").encode()).hexdigest(),
            "formula": formula(elements),
            "atom_count": len(elements),
            "elements": unique_elements,
            "charge": charge,
            "multiplicity": multiplicity,
        },
        "system_class": "synthetic_closed_shell_identity_fixture",
    })
    profiles = PROTOCOL_SUPPORT.profiles_fixture()
    for option in profiles["options"]:
        profile = option["method_profiles"][0]
        profile["basis_stack"][0]["elements"] = unique_elements
        profile["stages"] = task_types
        option["applicability"]["task_types"] = task_types
        option["applicability"]["system_classes"] = [request["system_class"]]
        if task_types == ["transition_state_optimization", "harmonic_frequency"]:
            option["task_plan"] = [
                {
                    "stage_type": "transition_state_optimization",
                    "profile_id": profile["profile_id"],
                    "required": True,
                    "acceptance_checks": ["exactly one reviewed imaginary mode"],
                },
                {
                    "stage_type": "harmonic_frequency",
                    "profile_id": profile["profile_id"],
                    "required": True,
                    "acceptance_checks": ["complete harmonic modes"],
                },
            ]
    request_path = root / f"{stem}-request.json"
    profiles_path = root / f"{stem}-profiles.json"
    options_path = root / f"{stem}-options.json"
    write(request_path, request)
    write(profiles_path, profiles)
    options = PROTOCOL.build_options(request_path, profiles_path)
    PROTOCOL.write_new_json(options_path, options)
    decision_path = root / f"{stem}-protocol-decision.json"
    write(decision_path, {
        "decision": "selected", "tier": tier, "explicit_confirmation": True,
        "decision_reason": "Synthetic offline integration fixture selection.",
    })
    selection = PROTOCOL.build_selection(options_path, tier, decision_path)
    selection_path = root / f"{stem}-selection.json"
    PROTOCOL.write_new_json(selection_path, selection)
    selected = PROTOCOL.get_selected_option(options, selection)
    return options_path, selection_path, options, selection, selected


def route_mapping(report: dict, selected: dict, selection: dict) -> tuple[dict, dict]:
    profile = selected["method_profiles"][0]
    used_tasks = [
        {
            "task_index": index,
            "stage_type": task["stage_type"],
            "profile_id": task["profile_id"],
        }
        for index, task in enumerate(selected["task_plan"])
    ]
    protocol_binding = {
        "selected_option": copy.deepcopy(selection["selected_option"]),
        "used_profile_ids": [profile["profile_id"]],
        "used_tasks": used_tasks,
    }
    task_mappings = []
    for task in used_tasks:
        stage = task["stage_type"]
        evidence = (
            ["opt_ts"] if stage == "transition_state_optimization"
            else ["frequency"] if stage == "harmonic_frequency"
            else ["minimum_opt", "frequency"]
        )
        task_mappings.append({**task, "route_evidence": evidence, "human_confirmed": True})
    mapping = {
        "exact_route": report["route"],
        "method": {"route_value": "hf", "profile_id": profile["profile_id"], "selected_value": copy.deepcopy(profile["functional_or_method"]), "human_confirmed": True},
        "basis": {"route_value": "sto-3g", "profile_id": profile["profile_id"], "selected_value": copy.deepcopy(profile["basis_stack"]), "human_confirmed": True},
        "solvent": {"route_value": "none", "profile_id": profile["profile_id"], "selected_value": copy.deepcopy(profile["solvation"]), "human_confirmed": True},
        "scf": {"route_value": "default", "profile_id": profile["profile_id"], "selected_value": copy.deepcopy(profile["scf"]), "human_confirmed": True},
        "tasks": task_mappings,
        "explicit_confirmation": True,
    }
    return protocol_binding, mapping


class ProtectedQST3RealChainTests(unittest.TestCase):
    maxDiff = None

    def minimum_lineage(
        self, root: Path, minimum: dict, state: dict, *, source_kind: str = "conformer_selection",
    ) -> Path:
        stem = minimum["minimum_id"]
        elements = [atom["element"] for atom in state["atoms"]]
        xyz_path = root / minimum["optimized_coordinates"]["path"]
        xyz_atoms = LINEAGE.parse_xyz(xyz_path)
        options_path, selection_path, options, selection, selected = protocol_files(
            root, stem=f"{stem}-minimum-protocol",
            task_types=["optimization", "frequency"],
            elements=elements, charge=minimum["formal_charge"],
            multiplicity=minimum["multiplicity"], tier="strict",
        )
        input_path = root / f"{stem}.gjf"
        input_path.write_text(
            "%chk=" + stem + ".chk\n%mem=12GB\n%nprocshared=8\n"
            "#p hf/sto-3g opt freq\n\nminimum fixture\n\n0 1\n"
            + "\n".join(
                f"{atom['element']} {atom['x']} {atom['y']} {atom['z']}"
                for atom in xyz_atoms
            )
            + "\n\n",
            encoding="utf-8",
        )
        report = PBS.parse_gaussian(input_path)
        binding, mapping = route_mapping(report, selected, selection)
        binding.update({
            "options_sha256": PBS.sha256(options_path),
            "options_payload_sha256": options["proposal_payload_sha256"],
            "selection_sha256": PBS.sha256(selection_path),
            "selection_payload_sha256": selection["selection_payload_sha256"],
        })
        review_draft = root / f"{stem}-input-review.draft.json"
        review_path = root / f"{stem}-input-review.json"
        receipt_path = root / f"{stem}-input-approval.json"
        write(review_draft, {
            "schema": PBS.INPUT_REVIEW_SCHEMA,
            "review_id": f"{stem}_review", "work_kind": "minimum",
            "protocol_task_types": selection["scope_binding"]["task_types"],
            "protocol_binding": binding, "route_profile_mapping": mapping,
            "protocol_family_completion": False,
            "approved_input": PBS._input_approval_facts(report),
            "decision": {"status": "accepted_exact_input", "explicit_confirmation": True, "reviewer": "offline fixture", "reviewed_at": "2030-01-01T00:00:00Z", "rationale": "Real-file zero-network regression."},
            "calculation_ready": False, "no_submission_authorization": True,
            "payload_sha256": None,
        })
        PBS.finalize_input_review(review_draft, review_path)
        PBS.build_input_approval_receipt(
            options_path, selection_path, review_path, input_path, receipt_path,
            f"{stem}_receipt",
        )
        ensemble_path = root / f"{stem}-ensemble.json"
        ensemble_path.write_text("{}\n", encoding="utf-8")
        origin_path = root / f"{stem}-conformer-selection.json"
        write(origin_path, {
            "schema": "gaussian-conformer-selection-receipt/1",
            "candidate_only": True, "calculation_ready": False,
            "no_submission_authorization": True,
            "selection_is_not_authorization": True,
            "workflow_states": {"human_selected": True, "input_draft_generated": True, "exact_input_approved": False, "submission_authorized": False, "result_accepted": False},
            "selection": {"ensemble": ensemble_path.name, "ensemble_sha256": file_sha(ensemble_path), "ensemble_size_bytes": ensemble_path.stat().st_size},
            "gaussian_input": input_path.name, "gaussian_input_sha256": file_sha(input_path), "gaussian_input_size_bytes": input_path.stat().st_size,
            "xyz_coordinates": xyz_path.name, "xyz_sha256": file_sha(xyz_path), "xyz_size_bytes": xyz_path.stat().st_size,
            "candidate_atom_elements": elements, "formula": formula(elements),
        })
        log_path = root / minimum["source_log"]["path"]
        result_path = root / minimum["result"]["path"]
        checkpoint_path = root / minimum["checkpoint"]["path"]
        project = (stem[:12] + "m").replace("-", "_")
        job_id = f"{len(stem)}.master"
        attempt_id = "qsub-attempt-" + hashlib.sha256(stem.encode()).hexdigest()
        text = log_path.read_text(encoding="utf-8")
        inspection = {
            "schema": "gaussian-job-inspection/2", "project": project,
            "job_id": job_id, "state": "completed",
            "collected_at": "2030-01-01T00:01:00Z",
            "source": "single_remote_read_only_snapshot", "freshness": "fresh",
            "transport_classification": "success", "transport_returncode": 0,
            "termination_counts_known": True, "evidence_conflict": False,
            "process_alive": False, "log_size": log_path.stat().st_size,
            "full_normal_termination_count": text.count("Normal termination of Gaussian"),
            "full_error_termination_count": text.count("Error termination"),
        }
        inspection["evidence_sha256"] = LINEAGE.transport_digest(inspection)
        terminal = {
            "schema": "gaussian-terminal-inspection-receipt/1",
            "project": project, "job_id": job_id, "input_stem": input_path.stem,
            "input_sha256": file_sha(input_path), "attempt_id": attempt_id,
            "terminal_state": "completed", "collected_at": inspection["collected_at"],
            "inspection_evidence_sha256": inspection["evidence_sha256"],
            "inspection": inspection, "scientific_acceptance": False,
        }
        terminal["receipt_sha256"] = LINEAGE.transport_digest(terminal)
        terminal_path = root / f"{stem}-terminal.json"; write(terminal_path, terminal)
        artifacts = {
            path.name: {"sha256": file_sha(path), "size": path.stat().st_size}
            for path in (log_path, checkpoint_path, result_path, xyz_path)
        }
        snapshot = {
            "schema": "gaussian-fetch-snapshot/1", "project": project,
            "job_id": job_id, "input_sha256": file_sha(input_path),
            "snapshot_complete": True,
            "terminal_inspection_receipt_sha256": terminal["receipt_sha256"],
            "per_hop_sha256_verified": True, "artifacts": artifacts,
            "per_hop": {
                name: {"server_sha256": value["sha256"], "rtwin_sha256": value["sha256"], "mac_sha256": value["sha256"], "size": value["size"]}
                for name, value in artifacts.items()
                if name in {log_path.name, checkpoint_path.name}
            },
        }
        snapshot["payload_sha256"] = LINEAGE.transport_digest(snapshot)
        snapshot_path = root / f"{stem}-snapshot.json"; write(snapshot_path, snapshot)
        job = {
            "schema": "gaussian-rtwin-pbs/1", "project": project,
            "job_id": job_id, "status": "completed", "results_fetched": True,
            "input_sha256": file_sha(input_path),
            "execution_batch": {"attempt_id": attempt_id},
            "terminal_inspection_receipt_sha256": terminal["receipt_sha256"],
            "fetch_snapshot_sha256": file_sha(snapshot_path),
            "fetch_snapshot_size": snapshot_path.stat().st_size,
        }
        job_path = root / f"{stem}-job.json"; write(job_path, job)
        review_path = root / f"{stem}-lineage-review.json"
        stable_ids = [atom["atom_id"] for atom in state["atoms"]]
        write(review_path, {
            "schema": LINEAGE.REVIEW_SCHEMA, "lineage_id": f"{stem}_lineage",
            "minimum_id": stem, "state_id": minimum["state_id"],
            "workflow_settings": {"temperature_k": 298.15, "standard_state": "1M", "expected_stages": 3},
            "stable_atom_ids": stable_ids,
            "atom_mapping": [
                {"atom_id": atom_id, "candidate_index": index, "input_index": index, "result_index": index, "element": element}
                for index, (atom_id, element) in enumerate(zip(stable_ids, elements), 1)
            ],
            "structure_review": {"identity_label": stem, "formula": formula(elements), "connectivity": [], "stereochemistry": [], "connectivity_reviewed": True, "stereochemistry_reviewed": True},
            "decision": "accepted", "explicit_human_review": True,
            "reviewer": "offline fixture", "rationale": "Real-file zero-network regression.",
            "reviewed_at": "2030-01-01T00:02:00Z",
        })
        lineage_path = root / f"{stem}-lineage.json"
        origin_binding = {"selection": origin_path} if source_kind == "conformer_selection" else {"reviewed_result": review_path}
        LINEAGE.build(root, {
            **origin_binding, "input_approval": receipt_path,
            "input": input_path, "job": job_path, "result": result_path,
            "raw_log": log_path, "checkpoint": checkpoint_path,
            "optimized_coordinates": xyz_path,
            "terminal_inspection_receipt": terminal_path,
            "fetch_snapshot": snapshot_path,
        }, review_path, lineage_path, source_kind=source_kind)
        return lineage_path

    def test_real_file_maturity_to_qst3_receipt_chain_is_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            maturity_fixture = MATURITY_SUPPORT.ScientificMaturityV2Tests(
                "test_positive_pilot_roundtrip_schemas_and_v1_compatibility"
            )
            maturity_fixture.setUp()
            original_base_review = maturity_fixture.base.review

            def base_review_with_selected_fixture_medoid(*args, **kwargs):
                value = original_base_review(*args, **kwargs)
                for minimum in value["minimum_records"]:
                    minimum["conformer_origin"] = {
                        "scope": "accepted_minimum_result_review",
                        "source_id": minimum["minimum_id"] + "_lineage",
                        "ts_derivation_allowed": True,
                    }
                return value

            maturity_fixture.base.review = base_review_with_selected_fixture_medoid
            plan_path, base_gate_path, base_review, mechanism = maturity_fixture.formal_base_context(root)
            review = maturity_fixture.review_v2(root, base_gate_path, base_review, mechanism)
            states = {state["state_id"]: state for state in mechanism["states"]}
            base_minima = {item["minimum_id"]: item for item in base_review["minimum_records"]}
            for item in review["minimum_evidence"]:
                lineage_path = self.minimum_lineage(
                    root, base_minima[item["minimum_id"]], states[item["state_id"]],
                    source_kind="reviewed_result",
                )
                item["selected_candidate_id"] = item["minimum_id"] + "_lineage"
                item["conformer_handoff"] = None
                item["minimum_lineage"] = MATURITY_SUPPORT.binding(lineage_path, root)
            _, _, gate_path = maturity_fixture.build_overlay(root, review, base_gate_path)
            gate_document = MATURITY.validate_gate(gate_path)
            self.assertTrue(
                gate_document["edge_gates"][0]["formal_scientifically_ready"],
                json.dumps({
                    "edge": gate_document["edge_gates"][0]["formal_blockers"],
                    "minima": gate_document["minimum_gates"],
                }, indent=2),
            )
            input_action_path = root / "ts-input-action.json"
            submission_action_path = root / "ts-submission-action.json"
            MATURITY.build_action(gate_path, "edge_activation", "ts_freq_activation", "ts_input", input_action_path)
            MATURITY.build_action(gate_path, "edge_activation", "ts_freq_activation", "ts_submission", submission_action_path)
            endpoints = MATURITY.resolve_ts_endpoint_minimum_lineages(input_action_path)
            reactant_atoms = endpoints["reactant"]["coordinates"]
            product_atoms = endpoints["product"]["coordinates"]
            mapping = {item["from_atom_id"]: item["to_atom_id"] for item in endpoints["atom_mapping"]}
            product_ids = endpoints["product"]["stable_atom_ids"]
            atom_map = [product_ids.index(mapping[atom_id]) + 1 for atom_id in endpoints["reactant"]["stable_atom_ids"]]
            product_raw_atoms = [product_atoms[index - 1] for index in atom_map]
            guess_atoms = copy.deepcopy(reactant_atoms)
            guess_atoms[0]["x"] = (reactant_atoms[0]["x"] + product_raw_atoms[0]["x"]) / 2

            def cartesian(path: Path, atoms: list[dict]) -> None:
                path.write_text(
                    "#p hf/sto-3g\n\nfixture\n\n0 1\n"
                    + "\n".join(f"{a['element']} {a['x']} {a['y']} {a['z']}" for a in atoms)
                    + "\n\n", encoding="utf-8",
                )

            role_paths = {role: root / f"{role}.gjf" for role in ("reactant", "product", "ts")}
            cartesian(role_paths["reactant"], reactant_atoms)
            cartesian(role_paths["product"], product_raw_atoms)
            cartesian(role_paths["ts"], guess_atoms)
            structures = {role: TS.parse_cartesian_input(path) for role, path in role_paths.items()}
            atom_audit = TS.validate_input_family("qst3", structures, atom_map)
            atom_audit["qst3_guess_review"] = {
                "decision": "reviewed_guess", "confirmed": True, "minimum_claim": False,
                "reviewed_structure_sha256": structures["ts"]["sha256"],
                "reviewer": "offline fixture", "rationale": "Guess only; no minimum claim.",
            }
            atom_audit_path = root / "qst3-atom-audit.json"; write(atom_audit_path, atom_audit)
            route = "#p hf/sto-3g opt=(qst3,calcfc) freq"
            qst_input = root / "h30c4q3.gjf"
            blocks = []
            for role, atoms in (("reactant", reactant_atoms), ("product", product_raw_atoms), ("guess", guess_atoms)):
                blocks.append(
                    f"{role}\n\n0 1\n" + "\n".join(
                        f"{a['element']} {a['x']} {a['y']} {a['z']}" for a in atoms
                    )
                )
            qst_input.write_text(
                "%chk=h30c4q3.chk\n%mem=50GB\n%nprocshared=22\n" + route
                + "\n\n" + "\n\n".join(blocks) + "\n\n",
                encoding="utf-8",
            )
            known_good = root / "known-good-qst3.txt"
            known_good.write_text("Gaussian 16 Revision A.03\nNormal termination of Gaussian 16\n", encoding="utf-8")
            revision = {
                "schema": TS.QST_REVISION_EVIDENCE_SCHEMA,
                "evidence_id": "real_file_qst3_revision_fixture",
                "installed_revision": "Gaussian 16 Revision A.03",
                "verification_status": "verified",
                "known_good_example": {
                    "mode": "qst3",
                    "input": {"path": qst_input.name, "sha256": file_sha(qst_input), "size_bytes": qst_input.stat().st_size},
                    "source": {"path": known_good.name, "sha256": file_sha(known_good), "size_bytes": known_good.stat().st_size},
                    "source_kind": "successful_installed_revision_run",
                    "usable_status": "known_usable",
                    "source_assertion": "known_usable_for_installed_revision",
                    "support_binding": {"syntax_profile": "gaussian-qst-cartesian-multistructure/1", "exact_assertion": "exact_qst_multistructure_syntax_supported_for_installed_revision", "source_locator": "Normal termination of Gaussian 16", "reviewed": True, "reviewer": "offline fixture", "rationale": "Synthetic installed-revision syntax evidence."},
                },
                "limitations": ["Offline fixture; no live authority."],
                "no_submission_authorization": True,
            }
            revision["evidence_payload_sha256"] = TS._canonical_payload_sha256(revision, "evidence_payload_sha256")
            revision_path = root / "revision.json"; write(revision_path, revision)
            qst_audit_path = root / "qst3-raw-audit.json"
            TS.audit_raw_qst_input(
                qst_input, file_sha(qst_input), atom_audit_path, file_sha(atom_audit_path),
                revision_path, file_sha(revision_path), qst_audit_path,
            )
            input_action = MATURITY.validate_action(input_action_path)
            gate = MATURITY.validate_gate(gate_path)
            family = TS.create_family_manifest(
                atom_audit,
                {
                    "workflow_id": "h30_c4_qst3_real_file", "project_prefix": "h30c4q3",
                    "expected_reactant_identity": "accepted reactant minimum",
                    "expected_product_identity": "accepted product minimum",
                    "coordinate_changes": ["H transfer fixture"],
                    "routes": {"ts_freq": route, "irc_forward": "#p hf/sto-3g irc=(forward,rcfc)", "irc_reverse": "#p hf/sto-3g irc=(reverse,rcfc)", "endpoint_opt_freq": "#p hf/sto-3g opt freq"},
                    "resource_tiers": {"ts_freq": "general", "irc": "general", "endpoint": "general"},
                    "temperature_k": 298.15, "standard_state": "1M",
                },
                maturity_check=input_action,
                maturity_binding={"path": gate_path.name, "sha256": file_sha(gate_path), "size_bytes": gate_path.stat().st_size, "schema": MATURITY.GATE_SCHEMA, "payload_sha256": gate["payload_sha256"]},
                edge_id="edge_activation", node_id="ts_freq_activation", pilot=False,
            )
            family_path = root / "family.json"; write(family_path, family)
            self.assertEqual(TS.validate_family_artifact(family_path), family)
            elements = [atom["element"] for atom in reactant_atoms]
            options_path, protocol_selection_path, options, protocol_selection, selected = protocol_files(
                root, stem="qst3", task_types=["transition_state_optimization", "harmonic_frequency"],
                elements=elements, charge=0, multiplicity=1, tier="standard",
            )
            report = LEGACY.parse_gaussian(qst_input)
            protocol_binding, mapping_review = route_mapping(report, selected, protocol_selection)
            protocol_binding.update({"options_sha256": LEGACY.sha256(options_path), "options_payload_sha256": options["proposal_payload_sha256"], "selection_sha256": LEGACY.sha256(protocol_selection_path), "selection_payload_sha256": protocol_selection["selection_payload_sha256"]})
            review_draft = root / "qst3-input-review.draft.json"
            review_path = root / "qst3-input-review.json"
            write(review_draft, {
                "schema": LEGACY.INPUT_REVIEW_SCHEMA, "review_id": "qst3_real_chain",
                "work_kind": "formal_ts", "protocol_task_types": protocol_selection["scope_binding"]["task_types"],
                "protocol_binding": protocol_binding, "route_profile_mapping": mapping_review,
                "protocol_family_completion": False,
                "approved_input": LEGACY._input_approval_facts(report),
                "decision": {"status": "accepted_exact_input", "explicit_confirmation": True, "reviewer": "offline fixture", "reviewed_at": "2030-01-01T00:03:00Z", "rationale": "Real-file zero-network regression."},
                "calculation_ready": False, "no_submission_authorization": True,
                "payload_sha256": None,
            })
            LEGACY.finalize_input_review(review_draft, review_path)
            authorization_path = root / "action-authorization.json"
            MATURITY.build_action_authorization(
                submission_action_path, qst_input, authorization_path,
                project="h30c4q3", work_kind="formal_ts", resource_tier="general",
                task_count=1, estimated_core_hours=88, planned_concurrency=1,
            )
            receipt_path = root / "qst3-input-approval.json"
            with mock.patch.object(LEGACY, "run", side_effect=AssertionError("network forbidden")), mock.patch.object(LEGACY.subprocess, "run", side_effect=AssertionError("qsub forbidden")):
                receipt = ADAPTER.build_receipt(
                    options_path=options_path, selection_path=protocol_selection_path,
                    review_path=review_path, input_path=qst_input,
                    qst_audit_path=qst_audit_path, family_path=family_path,
                    input_action_path=input_action_path,
                    submission_action_path=submission_action_path,
                    action_authorization_path=authorization_path,
                    output_path=receipt_path, receipt_id="qst3_real_file_receipt",
                )
                self.assertEqual(ADAPTER.validate_receipt(receipt_path), receipt)
            self.assertEqual(receipt["specialist_owner_binding"]["ts_family_sha256"], file_sha(family_path))
            self.assertEqual(receipt["specialist_owner_binding"]["atom_identity_mapping"]["declared_atom_map"], atom_map)
            self.assertEqual(receipt["specialist_owner_binding"]["coordinate_equivalence"], ADAPTER.COORDINATE_EQUIVALENCE)
            validated_input = LEGACY.validate_input_approval(
                receipt_path, qst_input, report, "formal_ts"
            )
            owner = receipt["specialist_owner_binding"]
            execution = {
                "batch_id": "offline-real-file-batch",
                "review_sha256": "1" * 64,
                "scientific_task_id": "scientific-task-" + "2" * 64,
                "attempt_id": "qsub-attempt-" + "3" * 64,
                "idempotency_key": "offline-real-file-qst3-attempt",
                "estimated_core_hours": 88.0,
                "estimated_core_hours_evidence": {
                    "source": "offline reviewed fixture estimate",
                    "sha256": "4" * 64,
                },
                "resource_binding": {
                    "policy_id": "offline-real-file-policy",
                    "policy_sha256": "5" * 64,
                    "gate_id": "offline-real-file-gate",
                    "gate_sha256": "6" * 64,
                    "resource_tier": "general", "cores": 22,
                    "memory_gb": 50, "walltime_seconds": 14400,
                },
            }
            live_scope = ADAPTER.expected_live_scope(
                receipt_path, qst_input, "h30c4q3", execution
            )
            maturity_projection = {
                "schema": ADAPTER.MATURITY_ACTION_SCHEMA,
                "edge_id": "edge_activation", "node_id": "ts_freq_activation",
                "pilot": False,
                "exact_action_authorization": {
                    "sha256": owner["scientific_action_authorization_sha256"],
                    "payload_sha256": owner[
                        "scientific_action_authorization_payload_sha256"
                    ],
                },
            }
            summary = LEGACY.live_approval_summary(
                "h30c4q3", report, maturity_projection,
                "formal_ts", validated_input,
            )
            summary["execution"] = execution
            schema, legacy_scope = LEGACY.expected_live_approval_scope(summary)
            self.assertEqual((schema, legacy_scope), (ADAPTER.LIVE_SCHEMA, live_scope))
            replay_summary = REPLAY._summary_from_approval({
                "schema": ADAPTER.LIVE_SCHEMA, "scope": live_scope,
            })
            self.assertEqual(
                LEGACY.expected_live_approval_scope(replay_summary),
                (schema, live_scope),
            )
            self.assertFalse(receipt["calculation_ready"])
            self.assertTrue(receipt["no_submission_authorization"])
            self.assertEqual(ADAPTER.production_effect_status()["qsub_calls"], 0)


if __name__ == "__main__":
    unittest.main()
