#!/usr/bin/env python3
"""Offline tests for the calculation-DAG and reaction-study index slice."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "calculation_dag.py"
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow"
REVIEW_TEMPLATE = FIXTURES / "calculation_plan_review.template.json"
PLAN_SCHEMA = ROOT / "contracts" / "reaction-workflow" / "calculation-plan.schema.json"
INDEX_SCHEMA = ROOT / "contracts" / "reaction-workflow" / "study-index.schema.json"
MAPPING_SCHEMA = ROOT / "contracts" / "reaction-workflow" / "calculation-target-mapping-review.schema.json"
UPDATE_SCHEMA = ROOT / "contracts" / "reaction-workflow" / "calculation-node-update.schema.json"
MAX_SUPERSEDED_PLAN_DEPTH = 128

SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SCHEMA_SPEC = importlib.util.spec_from_file_location("calculation_dag_schema_validator", SCHEMA_VALIDATOR_PATH)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA_VALIDATOR = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA_VALIDATOR)

MECHANISM_TEST_PATH = ROOT / "tests" / "test_mechanism_network.py"
MECHANISM_SPEC = importlib.util.spec_from_file_location("calculation_dag_mechanism_fixture", MECHANISM_TEST_PATH)
assert MECHANISM_SPEC and MECHANISM_SPEC.loader
MECHANISM_FIXTURE = importlib.util.module_from_spec(MECHANISM_SPEC)
MECHANISM_SPEC.loader.exec_module(MECHANISM_FIXTURE)

SUPPORT_TEST_PATH = ROOT / "tests" / "test_mechanism_support.py"
SUPPORT_SPEC = importlib.util.spec_from_file_location("calculation_dag_support_fixture", SUPPORT_TEST_PATH)
assert SUPPORT_SPEC and SUPPORT_SPEC.loader
SUPPORT_FIXTURE = importlib.util.module_from_spec(SUPPORT_SPEC)
SUPPORT_SPEC.loader.exec_module(SUPPORT_FIXTURE)

TS_PRECEDENT_TEST_PATH = ROOT / "tests" / "test_ts_precedent_map.py"
TS_PRECEDENT_SPEC = importlib.util.spec_from_file_location("calculation_dag_ts_precedent_fixture", TS_PRECEDENT_TEST_PATH)
assert TS_PRECEDENT_SPEC and TS_PRECEDENT_SPEC.loader
TS_PRECEDENT_FIXTURE = importlib.util.module_from_spec(TS_PRECEDENT_SPEC)
TS_PRECEDENT_SPEC.loader.exec_module(TS_PRECEDENT_FIXTURE)

ADAPTER_TEST_PATH = ROOT / "tests" / "test_calculation_artifacts.py"
ADAPTER_TEST_SPEC = importlib.util.spec_from_file_location("calculation_dag_adapter_fixture", ADAPTER_TEST_PATH)
assert ADAPTER_TEST_SPEC and ADAPTER_TEST_SPEC.loader
ADAPTER_FIXTURE = importlib.util.module_from_spec(ADAPTER_TEST_SPEC)
ADAPTER_TEST_SPEC.loader.exec_module(ADAPTER_FIXTURE)


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def rehash(value: dict[str, object]) -> None:
    payload = copy.deepcopy(value)
    payload.pop("payload_sha256", None)
    value["payload_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()


def exact_local_ref(path: Path, schema: str) -> dict[str, object]:
    document = load_json(path)
    return {
        "path": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "schema": schema,
        "payload_sha256": document["payload_sha256"],
    }


def by_id(items: list[dict[str, object]], key: str, value: str) -> dict[str, object]:
    return next(item for item in items if item[key] == value)


ReviewMutator = Callable[[dict[str, object]], None]


class CalculationDagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.upstream_root = cls.root / "upstream"
        cls.upstream_root.mkdir()
        helper = MECHANISM_FIXTURE.MechanismNetworkTests("test_help_is_offline_and_exposed")
        mechanism_path, _, result = helper.build_network(cls.upstream_root)
        if result.returncode != 0:  # pragma: no cover - reported as setup failure
            raise AssertionError(result.stderr or result.stdout)
        cls.paths = {
            "intake": cls.upstream_root / "intake.json",
            "registry": cls.upstream_root / "registry.json",
            "condition": cls.upstream_root / "condition.json",
            "mechanism": mechanism_path,
        }
        cls.upstream = {name: load_json(path) for name, path in cls.paths.items()}
        cls._work_index = 0

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def workdir(self, label: str) -> Path:
        type(self)._work_index += 1
        path = self.root / f"{type(self)._work_index:03d}_{label}"
        path.mkdir()
        return path

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def review_data(self, mutator: ReviewMutator | None = None) -> dict[str, object]:
        review = load_json(REVIEW_TEMPLATE)
        review["intake_payload_sha256"] = self.upstream["intake"]["payload_sha256"]
        review["species_registry_payload_sha256"] = self.upstream["registry"]["payload_sha256"]
        review["condition_model_payload_sha256"] = self.upstream["condition"]["payload_sha256"]
        review["mechanism_network_payload_sha256"] = self.upstream["mechanism"]["payload_sha256"]
        if mutator is not None:
            mutator(review)
        return review

    def local_upstream(self, work: Path) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for name, source in self.paths.items():
            target = work / f"{name}.json"
            if not target.exists():
                shutil.copyfile(source, target)
            result[name] = target
        return result

    def finalize_review(
        self,
        work: Path,
        mutator: ReviewMutator | None = None,
        *,
        stem: str = "calculation",
    ) -> tuple[Path, subprocess.CompletedProcess[str]]:
        draft = work / f"{stem}-review-draft.json"
        finalized = work / f"{stem}-review.json"
        write_json(draft, self.review_data(mutator))
        result = self.run_cli("finalize-review", str(draft), "--output", str(finalized))
        return finalized, result

    def build_plan(
        self,
        work: Path,
        mutator: ReviewMutator | None = None,
        *,
        support_path: Path | None = None,
        precedent_path: Path | None = None,
        superseded_plans: tuple[Path, ...] = (),
        stem: str = "calculation",
    ) -> tuple[Path, Path, subprocess.CompletedProcess[str]]:
        finalized, result = self.finalize_review(work, mutator, stem=stem)
        plan = work / f"{stem}-plan.json"
        if result.returncode != 0:
            return finalized, plan, result
        paths = self.local_upstream(work)
        command = [
            "build-plan",
            str(paths["intake"]),
            str(paths["registry"]),
            str(paths["condition"]),
            str(paths["mechanism"]),
            "--review",
            str(finalized),
        ]
        if support_path is not None:
            command.extend(("--mechanism-support", str(support_path)))
        if precedent_path is not None:
            command.extend(("--ts-precedent-map", str(precedent_path)))
        for old_plan in superseded_plans:
            command.extend(("--supersedes-plan", str(old_plan)))
        command.extend(("--output", str(plan)))
        return finalized, plan, self.run_cli(*command)

    def require_plan(
        self,
        label: str,
        mutator: ReviewMutator | None = None,
        *,
        superseded_plans: tuple[Path, ...] = (),
        stem: str = "calculation",
    ) -> tuple[Path, Path, dict[str, object]]:
        work = self.workdir(label)
        review, plan, result = self.build_plan(
            work, mutator, superseded_plans=superseded_plans, stem=stem,
        )
        self.assert_success(result)
        self.assertTrue(plan.is_file())
        return review, plan, load_json(plan)

    def build_target_import(self, work: Path) -> tuple[Path, dict[str, object], str]:
        work = work.resolve()
        helper = ADAPTER_FIXTURE.CalculationArtifactTests(
            "test_target_import_retains_all_dispositions_and_stable_external_keys"
        )
        chain = helper.make_input_chain(work)
        ledger_path, _candidates = helper.make_ledger(work, chain)
        target_path = work / "candidate-target-import.json"
        target_import = ADAPTER_FIXTURE.ADAPTER.build_target_import(
            chain["study_path"], ledger_path, target_path, "fixture_target_import"
        )
        candidate_id = chain["candidate"]["candidate_id"]
        selected = by_id(target_import["targets"], "candidate_id", candidate_id)
        return target_path, target_import, selected["external_target_key"]

    def mapping_review_draft(
        self,
        plan_path: Path,
        target_path: Path,
        external_target_key: str,
        *,
        update_id: str = "map_primary_candidate",
        node_id: str = "ts_candidate_primary",
        expected_node_kind: str = "ts_candidate",
        supersedes: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        plan = load_json(plan_path)
        return {
            "schema": "gaussian-reaction-calculation-target-mapping-review/1",
            "update_id": update_id,
            "target_plan": exact_local_ref(plan_path, "gaussian-reaction-calculation-plan/1"),
            "target_import": exact_local_ref(target_path, "gaussian-candidate-target-import/1"),
            "external_target_key": external_target_key,
            "locator": {
                "study_id": plan["study_id"],
                "plan_id": plan["plan_id"],
                "node_id": node_id,
            },
            "expected_node_kind": expected_node_kind,
            "update_kind": "candidate_inventory",
            "artifact_role": "candidate_target_import",
            "supersedes": supersedes or [],
            "review_decision": "accepted",
            "reviewer": "fixture_reviewer",
            "reviewed_at": "2026-07-16T12:00:00+08:00",
            "review_notes": ["Explicit external target to DAG node mapping; no readiness promotion."],
            "calculation_ready": False,
            "no_submission_authorization": True,
            "payload_sha256": None,
        }

    def assert_review_or_build_rejected(self, label: str, mutator: ReviewMutator, pattern: str) -> None:
        work = self.workdir(label)
        _, plan, result = self.build_plan(work, mutator)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertRegex((result.stderr or result.stdout).lower(), pattern)
        self.assertFalse(plan.exists())

    def test_help_is_offline_and_all_commands_are_exposed(self) -> None:
        for command in (
            "finalize-review", "build-plan", "validate-plan", "build-index", "validate-index",
            "finalize-target-mapping-review", "validate-target-mapping-review",
            "build-node-update", "validate-node-update",
        ):
            with self.subTest(command=command):
                result = self.run_cli(command, "--help")
                self.assert_success(result)
        source = TOOL.read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "import socket", "requests", "paramiko"):
            self.assertNotIn(forbidden, source)

    def test_build_validate_index_schemas_and_determinism(self) -> None:
        work = self.workdir("positive")
        review, first_plan, result = self.build_plan(work)
        self.assert_success(result)
        paths = self.local_upstream(work)
        second_plan = work / "calculation-plan-second.json"
        second = self.run_cli(
            "build-plan",
            str(paths["intake"]),
            str(paths["registry"]),
            str(paths["condition"]),
            str(paths["mechanism"]),
            "--review",
            str(review),
            "--output",
            str(second_plan),
        )
        self.assert_success(second)
        self.assertEqual(first_plan.read_bytes(), second_plan.read_bytes())

        plan = load_json(first_plan)
        self.assertEqual(
            {node["node_kind"] for node in plan["nodes"]},
            {
                "minimum", "conformer", "complex", "ts_candidate", "ts_freq",
                "irc_forward", "irc_reverse", "endpoint", "single_point",
                "thermochemistry", "sensitivity",
            },
        )
        self.assertEqual(plan["mechanism_support"], None)
        self.assertEqual(plan["ts_precedent_map"], None)
        self.assertTrue(all(node["executable"] is False for node in plan["nodes"]))
        self.assertFalse(plan["calculation_ready"])
        self.assertTrue(plan["no_submission_authorization"])
        for node in plan["nodes"]:
            if node["node_id"] in plan["coverage"]["active_node_ids"] and node["target"]["edge_ids"]:
                self.assertIn(
                    "ts_precedent_map_missing",
                    node["readiness"]["scientific"]["blocker_ids"],
                    node["node_id"],
                )
        blocker_text = " ".join(item["description"] for item in plan["blockers"]).lower()
        self.assertIn("mechanism", blocker_text)
        self.assertIn("precedent", blocker_text)
        self.assertEqual(plan["coverage"]["node_count"], len(plan["nodes"]))
        self.assertIn("minimum_legacy", plan["coverage"]["historical_node_ids"])
        self.assertIn("ts_candidate_alternative", plan["coverage"]["historical_node_ids"])

        position = {node_id: index for index, node_id in enumerate(plan["topological_order"])}
        for node in plan["nodes"]:
            for dependency in node["depends_on"]:
                self.assertLess(position[dependency], position[node["node_id"]])

        checked = self.run_cli("validate-plan", str(first_plan))
        self.assert_success(checked)
        self.assertFalse(json.loads(checked.stdout)["live_actions"])

        plan_schema = load_json(PLAN_SCHEMA)
        SCHEMA_VALIDATOR.validate_schema_document(plan_schema)
        SCHEMA_VALIDATOR._validate_schema_instance(plan, plan_schema, plan_schema)

        first_index = work / "study-index.json"
        built_index = self.run_cli("build-index", str(first_plan), "--output", str(first_index))
        self.assert_success(built_index)
        second_index = work / "study-index-second.json"
        self.assert_success(self.run_cli("build-index", str(first_plan), "--output", str(second_index)))
        self.assertEqual(first_index.read_bytes(), second_index.read_bytes())
        index = load_json(first_index)
        self.assertTrue(index["read_only"])
        self.assertFalse(index["calculation_ready"])
        self.assertTrue(index["no_submission_authorization"])
        self.assertEqual(index["coverage"], plan["coverage"])
        self.assertEqual(len(index["node_resume"]), len(plan["nodes"]))
        self.assertEqual(
            [stage["stage_id"] for stage in index["stage_gates"]],
            [
                "reaction_intake", "species_registry", "condition_model",
                "mechanism_network", "mechanism_support", "ts_precedent_map",
                "calculation_plan", "input_review", "live_approval",
            ],
        )
        stages = {stage["stage_id"]: stage for stage in index["stage_gates"]}
        self.assertEqual(stages["mechanism_network"]["status"], "accepted")
        self.assertEqual(stages["mechanism_support"]["status"], "missing")
        self.assertEqual(index["last_accepted_stage"], "mechanism_network")
        plan_blockers = {item["blocker_id"]: item for item in plan["blockers"]}
        for stage in index["stage_gates"]:
            for blocker_id in stage["blocker_ids"]:
                self.assertIn(blocker_id, plan_blockers, (stage["stage_id"], blocker_id))
        self.assertTrue(index["next_blockers"])
        self.assertTrue(index["next_safe_offline_action"].strip())
        for forbidden in ("qsub", "qdel", "ssh ", "submit", "cancel", "delete"):
            self.assertNotIn(forbidden, index["next_safe_offline_action"].lower())
        checked_index = self.run_cli("validate-index", str(first_index))
        self.assert_success(checked_index)
        self.assertFalse(json.loads(checked_index.stdout)["live_actions"])
        index_schema = load_json(INDEX_SCHEMA)
        SCHEMA_VALIDATOR.validate_schema_document(index_schema)
        SCHEMA_VALIDATOR._validate_schema_instance(index, index_schema, index_schema)

    def test_graph_cycles_missing_nodes_orphans_and_stage_order_fail_closed(self) -> None:
        def self_edge(review: dict[str, object]) -> None:
            node = by_id(review["nodes"], "node_id", "minimum_reactants")
            node["depends_on"] = ["minimum_reactants"]
            node["inputs"].append({
                "slot_id": "self_input", "artifact_role": "optimized_geometry",
                "source_node_id": "minimum_reactants", "required": True,
                "description": "Invalid self dependency.",
            })

        def missing(review: dict[str, object]) -> None:
            node = by_id(review["nodes"], "node_id", "conformer_reactants")
            node["depends_on"] = ["missing_node"]
            node["inputs"][0]["source_node_id"] = "missing_node"

        def cycle(review: dict[str, object]) -> None:
            node = by_id(review["nodes"], "node_id", "minimum_reactants")
            node["depends_on"] = ["conformer_reactants"]
            node["inputs"].append({
                "slot_id": "cycle_input", "artifact_role": "conformer_ensemble",
                "source_node_id": "conformer_reactants", "required": True,
                "description": "Invalid reverse dependency.",
            })

        def orphan(review: dict[str, object]) -> None:
            node = copy.deepcopy(by_id(review["nodes"], "node_id", "sensitivity_activation"))
            node.update({"node_id": "orphan_sensitivity", "label": "disconnected orphan sensitivity"})
            node["depends_on"] = []
            node["inputs"] = []
            node["outputs"] = [{
                "slot_id": "orphan_output", "artifact_role": "orphan_geometry",
                "description": "Invalid disconnected output.",
            }]
            review["nodes"].append(node)

        def later_stage(review: dict[str, object]) -> None:
            node = by_id(review["nodes"], "node_id", "minimum_legacy")
            node["depends_on"] = ["sensitivity_activation"]
            node["inputs"].append({
                "slot_id": "later_stage_input", "artifact_role": "sensitivity_evidence",
                "source_node_id": "sensitivity_activation", "required": True,
                "description": "Invalid later-stage dependency.",
            })

        def duplicate_node(review: dict[str, object]) -> None:
            review["nodes"].append(copy.deepcopy(review["nodes"][0]))

        def duplicate_slot(review: dict[str, object]) -> None:
            node = by_id(review["nodes"], "node_id", "thermochemistry_activation")
            node["inputs"][1]["slot_id"] = node["inputs"][0]["slot_id"]

        def role_mismatch(review: dict[str, object]) -> None:
            node = by_id(review["nodes"], "node_id", "conformer_reactants")
            node["inputs"][0]["artifact_role"] = "missing_output_role"

        cases = (
            ("self", self_edge, r"self|itself"),
            ("missing", missing, r"missing|unknown"),
            ("cycle", cycle, r"cycle|acyclic"),
            ("orphan", orphan, r"orphan|disconnected"),
            ("stage", later_stage, r"stage|later|order"),
            ("duplicate_node", duplicate_node, r"duplicate.*node|node.*duplicate"),
            ("duplicate_slot", duplicate_slot, r"duplicate.*slot|slot.*duplicate"),
            ("role_mismatch", role_mismatch, r"role|output"),
        )
        for label, mutator, pattern in cases:
            with self.subTest(case=label):
                self.assert_review_or_build_rejected(f"graph_{label}", mutator, pattern)

    def test_alternative_and_supersession_contracts_fail_closed(self) -> None:
        def selected_nonmember(review: dict[str, object]) -> None:
            review["alternative_groups"][0]["selected_node_ids"] = ["minimum_reactants"]

        def group_mismatch(review: dict[str, object]) -> None:
            by_id(review["nodes"], "node_id", "ts_candidate_primary")["alternative_group_id"] = None

        def empty_select_one(review: dict[str, object]) -> None:
            review["alternative_groups"][0]["selected_node_ids"] = []

        def self_supersession(review: dict[str, object]) -> None:
            review["supersessions"][0]["superseded_node_ids"] = ["minimum_reactants"]

        def missing_superseded(review: dict[str, object]) -> None:
            review["supersessions"][0]["superseded_node_ids"] = ["missing_node"]

        def active_superseded(review: dict[str, object]) -> None:
            by_id(review["nodes"], "node_id", "minimum_legacy")["disposition"] = "planned"

        def supersession_cycle(review: dict[str, object]) -> None:
            by_id(review["nodes"], "node_id", "minimum_reactants")["disposition"] = "superseded"
            review["supersessions"].append({
                "supersession_id": "legacy_supersession_cycle",
                "superseding_node_id": "minimum_legacy",
                "superseded_node_ids": ["minimum_reactants"],
                "rationale": "Invalid cycle fixture.",
            })

        cases = (
            ("alternative_member", selected_nonmember, r"selected|member|alternative"),
            ("group_mismatch", group_mismatch, r"group|alternative"),
            ("empty_select_one", empty_select_one, r"select_one|selected|exactly"),
            ("self_supersession", self_supersession, r"self|supersed"),
            ("missing_superseded", missing_superseded, r"missing|unknown|supersed"),
            ("active_superseded", active_superseded, r"disposition|supersed"),
            ("supersession_cycle", supersession_cycle, r"cycle|acyclic|remain active"),
        )
        for label, mutator, pattern in cases:
            with self.subTest(case=label):
                self.assert_review_or_build_rejected(f"relation_{label}", mutator, pattern)

    def test_required_slots_roles_single_point_cardinality_and_target_continuity_fail_closed(self) -> None:
        def required_without_source(review: dict[str, object]) -> None:
            by_id(review["nodes"], "node_id", "minimum_reactants")["inputs"].append({
                "slot_id": "required_external_geometry",
                "artifact_role": "reviewed_starting_geometry",
                "source_node_id": None,
                "required": True,
                "description": "A required input cannot be left without an exact producer.",
            })

        def duplicate_output_role(review: dict[str, object]) -> None:
            by_id(review["nodes"], "node_id", "minimum_reactants")["outputs"].append({
                "slot_id": "second_minimum_geometry",
                "artifact_role": "optimized_geometry",
                "description": "A second slot with an ambiguous duplicate artifact role.",
            })

        def single_point_over_cardinality(review: dict[str, object]) -> None:
            target = by_id(review["nodes"], "node_id", "single_point_activated")["target"]
            target["state_ids"] = ["state_activated", "state_reactants"]
            target["edge_ids"] = ["edge_activation"]

        def dependency_target_discontinuity(review: dict[str, object]) -> None:
            target = by_id(review["nodes"], "node_id", "ts_freq_activation")["target"]
            target["edge_ids"] = ["edge_direct"]
            target["network_ids"] = ["network_direct"]

        def edge_single_point_from_minimum(review: dict[str, object]) -> None:
            node = by_id(review["nodes"], "node_id", "single_point_activated")
            node["target"]["state_ids"] = []
            node["target"]["edge_ids"] = ["edge_activation"]
            node["depends_on"] = ["minimum_reactants"]
            node["inputs"] = [{
                "slot_id": "minimum_geometry_for_edge",
                "artifact_role": "optimized_geometry",
                "source_node_id": "minimum_reactants",
                "required": True,
                "description": "Invalid structural-only source for an edge-target single point.",
            }]

        def endpoint_wrong_selected_state_order(review: dict[str, object]) -> None:
            endpoint = by_id(review["nodes"], "node_id", "endpoint_activated")
            reactant = by_id(review["nodes"], "node_id", "endpoint_reactants")
            endpoint["chemical_state"]["atom_order"] = copy.deepcopy(
                reactant["chemical_state"]["atom_order"]
            )

        def endpoint_to_opposite_state(review: dict[str, object]) -> None:
            single_point = by_id(review["nodes"], "node_id", "single_point_activated")
            reactant = by_id(review["nodes"], "node_id", "minimum_reactants")
            single_point["target"]["state_ids"] = ["state_reactants"]
            single_point["target"]["atom_refs"] = copy.deepcopy(reactant["target"]["atom_refs"])
            single_point["chemical_state"] = copy.deepcopy(reactant["chemical_state"])

        cases = (
            ("required_without_source", required_without_source, r"required.*(source|producer)|source.*required"),
            ("duplicate_output_role", duplicate_output_role, r"duplicate.*(artifact.*role|output.*role)|ambiguous.*role"),
            ("single_point_cardinality", single_point_over_cardinality, r"single.point.*exactly one|target.*cardinality"),
            ("dependency_target", dependency_target_discontinuity, r"target.*(mismatch|continuity)|depend.*(edge|network|target)"),
            ("edge_single_point_source", edge_single_point_from_minimum, r"single.point.*edge.*ts.freq|edge target.*predecessor"),
            ("endpoint_atom_order", endpoint_wrong_selected_state_order, r"endpoint|atom.order|target.*state"),
            ("endpoint_continuity", endpoint_to_opposite_state, r"continuity|depend.*state|target.*state"),
        )
        for label, mutator, pattern in cases:
            with self.subTest(case=label):
                self.assert_review_or_build_rejected(f"closed_semantics_{label}", mutator, pattern)

    def test_valid_edge_single_point_inherits_precedent_gate(self) -> None:
        def edge_single_point(review: dict[str, object]) -> None:
            node = by_id(review["nodes"], "node_id", "single_point_activated")
            node["target"]["state_ids"] = []
            node["target"]["edge_ids"] = ["edge_activation"]
            node["depends_on"] = ["ts_freq_activation"]
            node["inputs"] = [{
                "slot_id": "ts_frequency_source",
                "artifact_role": "ts_frequency_evidence",
                "source_node_id": "ts_freq_activation",
                "required": True,
                "description": "Reviewed edge-target stationary geometry source.",
            }]

        _, _, plan = self.require_plan("edge_single_point_precedent", edge_single_point)
        node = by_id(plan["nodes"], "node_id", "single_point_activated")
        self.assertIn("ts_precedent_map_missing", node["readiness"]["scientific"]["blocker_ids"])

    def test_blocked_plan_review_propagates_to_every_active_node(self) -> None:
        def blocked_review(review: dict[str, object]) -> None:
            review["review_decision"] = "blocked"
            review["review_notes"] = ["The reviewed calculation plan is explicitly blocked."]

        _, _, plan = self.require_plan("blocked_plan_review", blocked_review)
        blocker_descriptions = {
            item["blocker_id"]: item["description"] for item in plan["blockers"]
        }
        review_blocker_ids = {
            blocker_id for blocker_id, description in blocker_descriptions.items()
            if re.search(r"review.*blocked|blocked.*review", description.lower())
        }
        self.assertTrue(review_blocker_ids, "blocked review must create an explicit plan blocker")
        for node in plan["nodes"]:
            if node["disposition"] not in {"planned", "retained"}:
                continue
            self.assertEqual(node["readiness"]["scientific"]["status"], "blocked")
        minimum = by_id(plan["nodes"], "node_id", "minimum_reactants")
        self.assertTrue(
            review_blocker_ids.intersection(minimum["readiness"]["scientific"]["blocker_ids"]),
            "a root active node must not bypass the blocked plan review",
        )

    def test_reviewed_with_blockers_upstream_gate_propagates_to_node_readiness(self) -> None:
        work = self.workdir("blocked_upstream_gate")
        helper = MECHANISM_FIXTURE.MechanismNetworkTests("test_help_is_offline_and_exposed")
        intake_path, registry_path, _, intake, registry, _ = helper.build_upstream(work)

        condition_review = load_json(work / "condition_review.json")
        condition_review["review_decision"] = "accepted_with_blockers"
        condition_review["decisions"][0] = {
            "condition_id": "step_001_component_001",
            "treatment": "unresolved",
            "species_ids": [],
            "model": None,
            "rationale": "The explicit catalyst treatment remains unresolved for this adversarial fixture.",
            "review_status": "blocked",
        }
        blocked_condition_review = work / "condition-review-blocked.json"
        write_json(blocked_condition_review, condition_review)
        blocked_condition_path = work / "condition-blocked.json"
        built_condition = helper.run_tool(
            MECHANISM_FIXTURE.W1_TOOL,
            "build-condition-model",
            str(intake_path),
            str(registry_path),
            "--review",
            str(blocked_condition_review),
            "--output",
            str(blocked_condition_path),
        )
        self.assert_success(built_condition)
        blocked_condition = load_json(blocked_condition_path)
        self.assertEqual(blocked_condition["gate_status"], "reviewed_with_blockers")

        mechanism_review_path, mechanism_review = helper.review(
            work, intake, registry, blocked_condition,
        )
        mechanism_path = work / "mechanism-blocked-upstream.json"
        built_mechanism = helper.run_tool(
            MECHANISM_FIXTURE.W3_TOOL,
            "build",
            str(intake_path),
            str(registry_path),
            str(blocked_condition_path),
            "--review",
            str(mechanism_review_path),
            "--output",
            str(mechanism_path),
        )
        self.assert_success(built_mechanism)
        mechanism_artifact = load_json(mechanism_path)

        def exact_blocked_chain(review: dict[str, object]) -> None:
            review["intake_payload_sha256"] = intake["payload_sha256"]
            review["species_registry_payload_sha256"] = registry["payload_sha256"]
            review["condition_model_payload_sha256"] = blocked_condition["payload_sha256"]
            review["mechanism_network_payload_sha256"] = mechanism_artifact["payload_sha256"]

        finalized, result = self.finalize_review(work, exact_blocked_chain, stem="blocked-upstream")
        self.assert_success(result)
        plan_path = work / "blocked-upstream-plan.json"
        built_plan = self.run_cli(
            "build-plan",
            str(intake_path),
            str(registry_path),
            str(blocked_condition_path),
            str(mechanism_path),
            "--review",
            str(finalized),
            "--output",
            str(plan_path),
        )
        self.assert_success(built_plan)
        plan = load_json(plan_path)
        descriptions = {
            item["blocker_id"]: item["description"] for item in plan["blockers"]
        }
        minimum = by_id(plan["nodes"], "node_id", "minimum_reactants")
        minimum_blockers = " ".join(
            descriptions[blocker_id]
            for blocker_id in minimum["readiness"]["scientific"]["blocker_ids"]
        ).lower()
        self.assertRegex(
            minimum_blockers,
            r"upstream.*condition|condition.*(blocked|unresolved|blocker)",
        )

        index_path = work / "blocked-upstream-index.json"
        self.assert_success(self.run_cli("build-index", str(plan_path), "--output", str(index_path)))
        index = load_json(index_path)
        self.assertEqual(index["last_accepted_stage"], "species_registry")
        self.assertTrue(index["next_blockers"])
        plan_blockers = {item["blocker_id"]: item for item in plan["blockers"]}
        condition_stage = next(item for item in index["stage_gates"] if item["stage_id"] == "condition_model")
        self.assertTrue(condition_stage["blocker_ids"])
        expected_next = [plan_blockers[item] for item in sorted(condition_stage["blocker_ids"])]
        self.assertEqual(index["next_blockers"], expected_next)
        raw_descriptions = [item["description"] for item in blocked_condition["blockers"]]
        normalized_descriptions = [item["description"] for item in index["next_blockers"]]
        self.assertTrue(all(item["scope"] == "condition_model" for item in index["next_blockers"]))
        for description in raw_descriptions:
            self.assertTrue(any(description in normalized for normalized in normalized_descriptions), description)

    def test_divergent_exact_w1_and_w3_revision_chain_is_rejected(self) -> None:
        work = self.workdir("divergent_w1_w3_chain")
        helper = MECHANISM_FIXTURE.MechanismNetworkTests("test_help_is_offline_and_exposed")
        intake_path, registry_a_path, _, intake, registry_a, _ = helper.build_upstream(work)

        registry_b_review = load_json(work / "registry_review.json")
        registry_b_review["review_notes"].append("Second immutable registry revision for chain-coherence testing.")
        registry_b_review_path = work / "registry-review-b.json"
        write_json(registry_b_review_path, registry_b_review)
        registry_b_path = work / "registry-b.json"
        built_registry_b = helper.run_tool(
            MECHANISM_FIXTURE.W1_TOOL,
            "build-registry",
            str(intake_path),
            "--review",
            str(registry_b_review_path),
            "--output",
            str(registry_b_path),
        )
        self.assert_success(built_registry_b)
        registry_b = load_json(registry_b_path)
        self.assertNotEqual(registry_a["payload_sha256"], registry_b["payload_sha256"])

        condition_b_review = load_json(work / "condition_review.json")
        condition_b_review["registry_payload_sha256"] = registry_b["payload_sha256"]
        condition_b_review["review_notes"].append("Condition model is bound to registry revision B.")
        condition_b_review_path = work / "condition-review-b.json"
        write_json(condition_b_review_path, condition_b_review)
        condition_b_path = work / "condition-b.json"
        built_condition_b = helper.run_tool(
            MECHANISM_FIXTURE.W1_TOOL,
            "build-condition-model",
            str(intake_path),
            str(registry_b_path),
            "--review",
            str(condition_b_review_path),
            "--output",
            str(condition_b_path),
        )
        self.assert_success(built_condition_b)
        condition_b = load_json(condition_b_path)

        mechanism_b_review_path, _ = helper.review(work, intake, registry_b, condition_b)
        mechanism_b_path = work / "mechanism-b.json"
        built_mechanism_b = helper.run_tool(
            MECHANISM_FIXTURE.W3_TOOL,
            "build",
            str(intake_path),
            str(registry_b_path),
            str(condition_b_path),
            "--review",
            str(mechanism_b_review_path),
            "--output",
            str(mechanism_b_path),
        )
        self.assert_success(built_mechanism_b)
        mechanism_b = load_json(mechanism_b_path)

        def incoherent_chain(review: dict[str, object]) -> None:
            review["intake_payload_sha256"] = intake["payload_sha256"]
            review["species_registry_payload_sha256"] = registry_a["payload_sha256"]
            review["condition_model_payload_sha256"] = condition_b["payload_sha256"]
            review["mechanism_network_payload_sha256"] = mechanism_b["payload_sha256"]

        finalized, result = self.finalize_review(work, incoherent_chain, stem="divergent-chain")
        self.assert_success(result)
        plan_path = work / "divergent-chain-plan.json"
        built_plan = self.run_cli(
            "build-plan",
            str(intake_path),
            str(registry_a_path),
            str(condition_b_path),
            str(mechanism_b_path),
            "--review",
            str(finalized),
            "--output",
            str(plan_path),
        )
        self.assertNotEqual(built_plan.returncode, 0, built_plan.stdout)
        self.assertRegex(
            (built_plan.stderr or built_plan.stdout).lower(),
            r"w1|w3|chain|registry.*(mismatch|does not match|binding)|condition.*(mismatch|does not match|binding)",
        )
        self.assertFalse(plan_path.exists())

    def test_blocked_or_wrong_optional_evidence_cannot_launder_readiness(self) -> None:
        work = self.workdir("blocked_optional_evidence")
        support_path = work / "mechanism-support.json"
        support = {
            "schema": "gaussian-reaction-mechanism-support/1",
            "study_id": "mechanism_network_fixture",
            "mechanism_network_payload_sha256": "0" * 64,
            "support_status": "unsupported",
            "review_status": "blocked",
            "gate_status": "blocked",
            "blockers": [{
                "blocker_id": "support_wrong_network",
                "scope": "study",
                "description": "Support is bound to the wrong mechanism network and remains unsupported.",
                "required_for": ["scientific_readiness"],
            }],
            "calculation_ready": False,
            "no_submission_authorization": True,
            "payload_sha256": None,
        }
        rehash(support)
        write_json(support_path, support)

        precedent_path = work / "ts-precedent-map.json"
        precedent = {
            "schema": "gaussian-ts-precedent-map/1",
            "study_id": "mechanism_network_fixture",
            "mechanism_network_payload_sha256": self.upstream["mechanism"]["payload_sha256"],
            "review_status": "blocked",
            "gate_status": "blocked",
            "blockers": [{
                "blocker_id": "precedent_review_blocked",
                "scope": "study",
                "description": "The TS precedent map remains blocked by review.",
                "required_for": ["ts_candidate", "ts_freq", "irc", "endpoint"],
            }],
            "calculation_ready": False,
            "no_submission_authorization": True,
            "payload_sha256": None,
        }
        rehash(precedent)
        write_json(precedent_path, precedent)

        def bind_optional_evidence(review: dict[str, object]) -> None:
            review["mechanism_support_payload_sha256"] = support["payload_sha256"]
            review["ts_precedent_map_payload_sha256"] = precedent["payload_sha256"]

        _, plan_path, result = self.build_plan(
            work,
            bind_optional_evidence,
            support_path=support_path,
            precedent_path=precedent_path,
        )
        if result.returncode != 0:
            self.assertRegex(
                (result.stderr or result.stdout).lower(),
                r"support|precedent|network|unsupported|blocked|contract",
            )
            self.assertFalse(plan_path.exists())
            return

        plan = load_json(plan_path)
        for node_id in ("minimum_reactants", "ts_candidate_primary"):
            node = by_id(plan["nodes"], "node_id", node_id)
            self.assertEqual(node["readiness"]["scientific"]["status"], "blocked")
            self.assertTrue(node["readiness"]["scientific"]["blocker_ids"])

        index_path = work / "study-index.json"
        self.assert_success(self.run_cli("build-index", str(plan_path), "--output", str(index_path)))
        index = load_json(index_path)
        stages = {item["stage_id"]: item for item in index["stage_gates"]}
        self.assertNotEqual(stages["mechanism_support"]["status"], "accepted")
        self.assertNotEqual(stages["ts_precedent_map"]["status"], "accepted")
        self.assertTrue(index["next_blockers"])

    def test_owner_validated_optional_artifacts_retain_channel_mapping_gate(self) -> None:
        work = self.workdir("validated_ts_precedent")
        helper = TS_PRECEDENT_FIXTURE.TsPrecedentMapTests(
            "test_four_analogy_classes_and_novel_de_novo_plan_are_exactly_gated"
        )
        prepared, precedent_path, built_precedent = helper.build_map(work)
        self.assert_success(built_precedent)
        precedent = load_json(precedent_path)
        support_path = prepared["support_path"]
        support = prepared["support"]
        w1 = prepared["w1"]
        intake_path, registry_path, condition_path, mechanism_path = w1[:4]
        intake, registry, condition, mechanism_artifact = w1[4:]

        review = load_json(REVIEW_TEMPLATE)
        review["intake_payload_sha256"] = intake["payload_sha256"]
        review["species_registry_payload_sha256"] = registry["payload_sha256"]
        review["condition_model_payload_sha256"] = condition["payload_sha256"]
        review["mechanism_network_payload_sha256"] = mechanism_artifact["payload_sha256"]
        review["mechanism_support_payload_sha256"] = support["payload_sha256"]
        review["ts_precedent_map_payload_sha256"] = precedent["payload_sha256"]
        draft_path = work / "validated-precedent-review-draft.json"
        review_path = work / "validated-precedent-review.json"
        write_json(draft_path, review)
        self.assert_success(self.run_cli("finalize-review", str(draft_path), "--output", str(review_path)))

        plan_path = work / "validated-precedent-plan.json"
        self.assert_success(self.run_cli(
            "build-plan",
            str(intake_path),
            str(registry_path),
            str(condition_path),
            str(mechanism_path),
            "--review",
            str(review_path),
            "--mechanism-support",
            str(support_path),
            "--ts-precedent-map",
            str(precedent_path),
            "--output",
            str(plan_path),
        ))
        plan = load_json(plan_path)
        blocker_ids = {item["blocker_id"] for item in plan["blockers"]}
        self.assertNotIn("ts_precedent_map_missing", blocker_ids)
        self.assertNotIn("ts_precedent_validation_unavailable", blocker_ids)
        self.assertNotIn("ts_precedent_coverage_incomplete", blocker_ids)
        self.assertIn("mechanism_support_channel_mapping_missing", blocker_ids)
        edge_node = by_id(plan["nodes"], "node_id", "ts_candidate_primary")
        self.assertFalse(any("ts_precedent" in item for item in edge_node["readiness"]["scientific"]["blocker_ids"]))
        self.assertIn("mechanism_support_channel_mapping_missing", edge_node["readiness"]["scientific"]["blocker_ids"])
        self.assertFalse(edge_node["executable"])

        index_path = work / "validated-precedent-index.json"
        self.assert_success(self.run_cli("build-index", str(plan_path), "--output", str(index_path)))
        index = load_json(index_path)
        precedent_entry = next(item for item in index["artifacts"] if item["role"] == "ts_precedent_map")
        self.assertEqual(precedent_entry["status"], "current")
        support_entry = next(item for item in index["artifacts"] if item["role"] == "mechanism_support")
        self.assertEqual(support_entry["status"], "current")
        support_stage = next(item for item in index["stage_gates"] if item["stage_id"] == "mechanism_support")
        self.assertEqual(support_stage["status"], "blocked")
        self.assertEqual(support_stage["blocker_ids"], ["mechanism_support_channel_mapping_missing"])
        self.assertEqual(index["next_safe_offline_action"], "add_reviewed_edge_channel_mapping")
        self.assertFalse(index["calculation_ready"])
        self.assertTrue(index["no_submission_authorization"])

        mechanism_copy = work / "mechanism-copy.json"
        mechanism_copy.write_bytes(mechanism_path.read_bytes())
        mismatched_plan = work / "wrong-mechanism-path-plan.json"
        mismatched = self.run_cli(
            "build-plan",
            str(intake_path),
            str(registry_path),
            str(condition_path),
            str(mechanism_copy),
            "--review",
            str(review_path),
            "--mechanism-support",
            str(support_path),
            "--ts-precedent-map",
            str(precedent_path),
            "--output",
            str(mismatched_plan),
        )
        self.assertNotEqual(mismatched.returncode, 0)
        self.assertIn("exact selected artifact path", mismatched.stderr.lower())
        self.assertFalse(mismatched_plan.exists())

    def test_nonpromotable_support_preserves_owner_blockers_and_resume_action(self) -> None:
        for decision, expected_stage_status in (
            ("accepted_with_blockers", "accepted_with_blockers"),
            ("blocked", "blocked"),
        ):
            with self.subTest(decision=decision):
                work = self.workdir(f"support_gate_{decision}").resolve()
                helper = SUPPORT_FIXTURE.MechanismSupportTests(
                    "test_supported_conditional_unsupported_contradicted_and_novel_missing"
                )

                def block_every_channel(review: dict[str, object]) -> None:
                    review["review_decision"] = decision
                    for record in review["records"]:
                        record["exploration_decision"] = {
                            "status": "blocked",
                            "rationale": "Synthetic unresolved owner blocker for DAG propagation.",
                            "reviewer": "fixture_reviewer",
                            "reviewed_at": "2026-07-16T00:00:00+00:00",
                            "resolved_blockers": [],
                            "unresolved_blockers": ["Owner evidence gate remains unresolved."],
                            "resolved_conflict_record_ids": [],
                        }
                        record["claim_support_decision"] = {
                            "status": "rejected" if record["classification"]["category"] == "excluded" else "not_promoted",
                            "rationale": "No mechanism claim promotion while the owner gate is unresolved.",
                            "reviewer": "fixture_reviewer",
                            "reviewed_at": "2026-07-16T00:00:00+00:00",
                            "resolved_blockers": [],
                            "unresolved_blockers": ["Independent target-mechanism support is not established."],
                            "resolved_conflict_record_ids": [],
                        }

                prepared, support_path, built_support = helper.build_support(
                    work, review_mutator=block_every_channel
                )
                self.assert_success(built_support)
                support = load_json(support_path)
                self.assertTrue(support["blockers"])
                self.assertEqual(
                    support["gate_status"],
                    "blocked" if decision == "blocked" else "reviewed_with_blockers",
                )
                w1 = prepared["w1"]
                intake_path, registry_path, condition_path, mechanism_path = w1[:4]
                intake, registry, condition, mechanism_artifact = w1[4:]
                review = load_json(REVIEW_TEMPLATE)
                review["intake_payload_sha256"] = intake["payload_sha256"]
                review["species_registry_payload_sha256"] = registry["payload_sha256"]
                review["condition_model_payload_sha256"] = condition["payload_sha256"]
                review["mechanism_network_payload_sha256"] = mechanism_artifact["payload_sha256"]
                review["mechanism_support_payload_sha256"] = support["payload_sha256"]
                draft_path = work / "calculation-review-draft.json"
                review_path = work / "calculation-review.json"
                plan_path = work / "calculation-plan.json"
                write_json(draft_path, review)
                self.assert_success(self.run_cli(
                    "finalize-review", str(draft_path), "--output", str(review_path)
                ))
                self.assert_success(self.run_cli(
                    "build-plan",
                    str(intake_path), str(registry_path), str(condition_path), str(mechanism_path),
                    "--review", str(review_path),
                    "--mechanism-support", str(support_path),
                    "--output", str(plan_path),
                ))
                plan = load_json(plan_path)
                plan_blockers = {item["blocker_id"]: item for item in plan["blockers"]}
                self.assertIn("mechanism_support_not_promotable", plan_blockers)
                self.assertNotIn("mechanism_support_channel_mapping_missing", plan_blockers)
                normalized_support = [
                    item for item in plan["blockers"]
                    if item["scope"] == "mechanism_support" and item["blocker_id"] != "mechanism_support_not_promotable"
                ]
                self.assertTrue(normalized_support)
                for owner_blocker in support["blockers"]:
                    self.assertTrue(any(
                        owner_blocker["description"] in item["description"]
                        for item in normalized_support
                    ))
                self.assertTrue(any(
                    item["scope"] == "mechanism_network"
                    and "mechanism support" in item["description"].lower().replace("-", " ")
                    for item in plan["blockers"]
                ))

                index_path = work / "study-index.json"
                self.assert_success(self.run_cli("build-index", str(plan_path), "--output", str(index_path)))
                index = load_json(index_path)
                support_stage = next(item for item in index["stage_gates"] if item["stage_id"] == "mechanism_support")
                self.assertEqual(support_stage["status"], expected_stage_status)
                self.assertIn("mechanism_support_not_promotable", support_stage["blocker_ids"])
                self.assertEqual(index["last_accepted_stage"], "mechanism_network")
                self.assertEqual(index["next_safe_offline_action"], "review_mechanism_support_owner_blockers")
                self.assertEqual(
                    index["next_blockers"],
                    [plan_blockers[item] for item in sorted(support_stage["blocker_ids"])],
                )

    def test_reviewed_external_target_mapping_builds_append_only_node_update(self) -> None:
        work = self.workdir("dag_owned_target_mapping")
        _review, plan_path, built = self.build_plan(work)
        self.assert_success(built)
        plan_before = plan_path.read_bytes()
        target_path, _target_import, external_key = self.build_target_import(work)

        draft_path = work / "target-mapping-review-draft.json"
        review_path = work / "target-mapping-review.json"
        write_json(draft_path, self.mapping_review_draft(plan_path, target_path, external_key))
        self.assert_success(self.run_cli(
            "finalize-target-mapping-review", str(draft_path), "--output", str(review_path)
        ))
        finalized_review = load_json(review_path)
        self.assertEqual(finalized_review["external_target_key"], external_key)
        self.assertEqual(
            finalized_review["locator"],
            {
                "study_id": "mechanism_network_fixture",
                "plan_id": "fixture_calculation_plan",
                "node_id": "ts_candidate_primary",
            },
        )
        self.assert_success(self.run_cli("validate-target-mapping-review", str(review_path)))

        first_update = work / "candidate-node-update.json"
        self.assert_success(self.run_cli("build-node-update", str(review_path), "--output", str(first_update)))
        update = load_json(first_update)
        self.assertEqual(update["schema"], "gaussian-reaction-calculation-node-update/1")
        self.assertEqual(update["locator"], finalized_review["locator"])
        self.assertEqual(update["external_target"]["external_target_key"], external_key)
        self.assertEqual(update["expected_node_kind"], "ts_candidate")
        self.assertEqual(update["update_kind"], "candidate_inventory")
        self.assertEqual(update["artifact_role"], "candidate_target_import")
        self.assertFalse(update["calculation_ready"])
        self.assertTrue(update["no_submission_authorization"])
        self.assertNotEqual(external_key, update["locator"]["node_id"])
        self.assertEqual(plan_path.read_bytes(), plan_before)
        self.assert_success(self.run_cli("validate-node-update", str(first_update)))

        second_copy = work / "candidate-node-update-copy.json"
        self.assert_success(self.run_cli("build-node-update", str(review_path), "--output", str(second_copy)))
        self.assertEqual(first_update.read_bytes(), second_copy.read_bytes())

        for schema_path, document in (
            (MAPPING_SCHEMA, finalized_review),
            (UPDATE_SCHEMA, update),
        ):
            schema = load_json(schema_path)
            SCHEMA_VALIDATOR.validate_schema_document(schema)
            SCHEMA_VALIDATOR._validate_schema_instance(document, schema, schema)
        update_schema = load_json(UPDATE_SCHEMA)
        mapping_schema = load_json(MAPPING_SCHEMA)
        for field, unsupported in (
            ("expected_node_kind", "minimum"),
            ("update_kind", "input_review"),
            ("artifact_role", "input_handoff"),
        ):
            advertised_review = copy.deepcopy(finalized_review)
            advertised_review[field] = unsupported
            rehash(advertised_review)
            with self.assertRaises(SCHEMA_VALIDATOR.ContractError, msg=f"review:{field}"):
                SCHEMA_VALIDATOR._validate_schema_instance(advertised_review, mapping_schema, mapping_schema)
        for field, unsupported in (
            ("expected_node_kind", "minimum"),
            ("update_kind", "input_review"),
            ("artifact_role", "input_handoff"),
        ):
            advertised = copy.deepcopy(update)
            advertised[field] = unsupported
            rehash(advertised)
            with self.assertRaises(SCHEMA_VALIDATOR.ContractError, msg=field):
                SCHEMA_VALIDATOR._validate_schema_instance(advertised, update_schema, update_schema)
        wrong_artifact_schema = copy.deepcopy(update)
        wrong_artifact_schema["artifact"]["schema"] = "gaussian-candidate-input-handoff/1"
        rehash(wrong_artifact_schema)
        with self.assertRaises(SCHEMA_VALIDATOR.ContractError):
            SCHEMA_VALIDATOR._validate_schema_instance(wrong_artifact_schema, update_schema, update_schema)

        superseding_draft = work / "target-mapping-review-v2-draft.json"
        superseding_review = work / "target-mapping-review-v2.json"
        superseding_update = work / "candidate-node-update-v2.json"
        write_json(
            superseding_draft,
            self.mapping_review_draft(
                plan_path,
                target_path,
                external_key,
                update_id="map_primary_candidate_v2",
                supersedes=[exact_local_ref(first_update, "gaussian-reaction-calculation-node-update/1")],
            ),
        )
        self.assert_success(self.run_cli(
            "finalize-target-mapping-review", str(superseding_draft), "--output", str(superseding_review)
        ))
        self.assert_success(self.run_cli(
            "build-node-update", str(superseding_review), "--output", str(superseding_update)
        ))
        self.assert_success(self.run_cli("validate-node-update", str(superseding_update)))
        self.assertEqual(
            load_json(superseding_update)["supersedes"],
            [exact_local_ref(first_update, "gaussian-reaction-calculation-node-update/1")],
        )
        self.assertEqual(plan_path.read_bytes(), plan_before)

    def test_target_mapping_refuses_key_alias_bad_local_refs_forgery_and_overwrite(self) -> None:
        work = self.workdir("dag_target_mapping_adversarial")
        _review, plan_path, built = self.build_plan(work)
        self.assert_success(built)
        target_path, _target_import, external_key = self.build_target_import(work)

        def finalize_case(name: str, draft: dict[str, object]) -> tuple[Path, subprocess.CompletedProcess[str]]:
            draft_path = work / f"{name}-draft.json"
            review_path = work / f"{name}.json"
            write_json(draft_path, draft)
            return review_path, self.run_cli(
                "finalize-target-mapping-review", str(draft_path), "--output", str(review_path)
            )

        key_alias = self.mapping_review_draft(plan_path, target_path, "ts_candidate_primary")
        alias_review, finalized_alias = finalize_case("alias-key-review", key_alias)
        self.assertNotEqual(finalized_alias.returncode, 0)
        self.assertIn("external_target_key", finalized_alias.stderr)
        self.assertFalse(alias_review.exists())

        absolute_ref = self.mapping_review_draft(plan_path, target_path, external_key)
        absolute_ref["target_import"]["path"] = str(target_path.resolve())
        absolute_output, absolute_result = finalize_case("absolute-ref-review", absolute_ref)
        self.assertNotEqual(absolute_result.returncode, 0)
        self.assertRegex(absolute_result.stderr.lower(), r"local|relative|absolute")
        self.assertFalse(absolute_output.exists())

        null_payload = self.mapping_review_draft(plan_path, target_path, external_key)
        null_payload["target_import"]["payload_sha256"] = None
        null_output, null_result = finalize_case("null-payload-review", null_payload)
        self.assertNotEqual(null_result.returncode, 0)
        self.assertIn("payload_sha256", null_result.stderr)
        self.assertFalse(null_output.exists())

        wrong_kind = self.mapping_review_draft(
            plan_path, target_path, external_key, expected_node_kind="minimum"
        )
        wrong_review, finalized_wrong = finalize_case("wrong-kind-review", wrong_kind)
        self.assertNotEqual(finalized_wrong.returncode, 0)
        self.assertIn("expected_node_kind", finalized_wrong.stderr)
        self.assertFalse(wrong_review.exists())

        good_review, finalized_good = finalize_case(
            "good-mapping-review", self.mapping_review_draft(plan_path, target_path, external_key)
        )
        self.assert_success(finalized_good)
        good_update = work / "good-node-update.json"
        self.assert_success(self.run_cli("build-node-update", str(good_review), "--output", str(good_update)))
        overwrite = self.run_cli("build-node-update", str(good_review), "--output", str(good_update))
        self.assertNotEqual(overwrite.returncode, 0)
        self.assertIn("overwrite", overwrite.stderr.lower())

        forged = load_json(good_update)
        forged["external_target"]["candidate_id"] = "forged_candidate"
        rehash(forged)
        forged_path = work / "forged-node-update.json"
        write_json(forged_path, forged)
        checked = self.run_cli("validate-node-update", str(forged_path))
        self.assertNotEqual(checked.returncode, 0)
        self.assertRegex(checked.stderr.lower(), r"deterministic|reconstruction|differs")

        # A review copied beneath another root retains a valid self hash but
        # its relative bindings no longer identify the reviewed plan/import.
        # The update validator must not reinterpret those literals relative
        # to its own parent directory.
        nested = work / "nested-review-root"
        nested.mkdir()
        nested_review = nested / "good-mapping-review.json"
        nested_review.write_bytes(good_review.read_bytes())
        review_check = self.run_cli("validate-target-mapping-review", str(nested_review))
        self.assertNotEqual(review_check.returncode, 0)
        confused = load_json(good_update)
        nested_document = load_json(nested_review)
        confused["review_source"] = {
            "path": nested_review.relative_to(work).as_posix(),
            "sha256": hashlib.sha256(nested_review.read_bytes()).hexdigest(),
            "size_bytes": nested_review.stat().st_size,
            "schema": "gaussian-reaction-calculation-target-mapping-review/1",
            "payload_sha256": nested_document["payload_sha256"],
        }
        rehash(confused)
        confused_path = work / "root-confused-node-update.json"
        write_json(confused_path, confused)
        confused_check = self.run_cli("validate-node-update", str(confused_path))
        self.assertNotEqual(confused_check.returncode, 0)
        self.assertRegex(confused_check.stderr.lower(), r"artifact root|mapping review|missing")

    def test_invalid_mechanism_and_atom_references_fail_closed(self) -> None:
        def unknown_state(review: dict[str, object]) -> None:
            for node_id in ("minimum_reactants", "minimum_legacy"):
                by_id(review["nodes"], "node_id", node_id)["target"]["state_ids"] = ["state_missing"]

        def unknown_edge(review: dict[str, object]) -> None:
            for node_id in ("ts_candidate_primary", "ts_candidate_alternative"):
                by_id(review["nodes"], "node_id", node_id)["target"]["edge_ids"] = ["edge_missing"]

        def wrong_network(review: dict[str, object]) -> None:
            for node_id in ("ts_candidate_primary", "ts_candidate_alternative"):
                by_id(review["nodes"], "node_id", node_id)["target"]["network_ids"] = ["network_direct"]

        def unknown_basin(review: dict[str, object]) -> None:
            by_id(review["nodes"], "node_id", "sensitivity_activation")["target"]["reference_basin_ids"] = ["basin_missing"]

        def unknown_atom(review: dict[str, object]) -> None:
            for node_id in ("minimum_reactants", "minimum_legacy"):
                by_id(review["nodes"], "node_id", node_id)["target"]["atom_refs"][0]["atom_id"] = "r_missing"

        cases = (
            ("state", unknown_state, r"state.*(missing|unknown)|unknown.*state"),
            ("edge", unknown_edge, r"edge.*(missing|unknown)|unknown.*edge"),
            ("network", wrong_network, r"edge|network|outside"),
            ("basin", unknown_basin, r"basin.*(missing|unknown)|unknown.*basin"),
            ("atom", unknown_atom, r"atom.*(missing|unknown)|unknown.*atom"),
        )
        for label, mutator, pattern in cases:
            with self.subTest(case=label):
                self.assert_review_or_build_rejected(f"reference_{label}", mutator, pattern)

    def test_missing_chemical_state_is_blocked_but_mismatch_is_invalid(self) -> None:
        missing_cases = (
            ("charge", lambda state: state.__setitem__("formal_charge", None)),
            ("multiplicity", lambda state: state.__setitem__("multiplicity", None)),
            ("atom_order", lambda state: state.__setitem__("atom_order", None)),
        )
        for field, change in missing_cases:
            with self.subTest(missing=field):
                def mutate(review: dict[str, object], update=change) -> None:
                    update(by_id(review["nodes"], "node_id", "minimum_reactants")["chemical_state"])

                _, _, plan = self.require_plan(f"missing_{field}", mutate)
                node = by_id(plan["nodes"], "node_id", "minimum_reactants")
                self.assertEqual(node["readiness"]["scientific"]["status"], "blocked")
                blocker_ids = set(node["readiness"]["scientific"]["blocker_ids"])
                descriptions = " ".join(
                    item["description"] for item in plan["blockers"]
                    if item["blocker_id"] in blocker_ids
                ).lower()
                self.assertIn(field.replace("_", " ").split()[0], descriptions)

        def wrong_charge(review: dict[str, object]) -> None:
            by_id(review["nodes"], "node_id", "minimum_reactants")["chemical_state"]["formal_charge"] = 1

        def wrong_spin(review: dict[str, object]) -> None:
            by_id(review["nodes"], "node_id", "minimum_reactants")["chemical_state"]["multiplicity"] = 3

        def wrong_order(review: dict[str, object]) -> None:
            state = by_id(review["nodes"], "node_id", "minimum_reactants")["chemical_state"]
            state["atom_order"] = state["atom_order"][:-1]

        for label, mutator, pattern in (
            ("charge", wrong_charge, r"charge.*(mismatch|differ)|mismatch.*charge"),
            ("spin", wrong_spin, r"multiplicity.*(mismatch|differ)|mismatch.*multiplicity"),
            ("order", wrong_order, r"atom order|atom_order|cover"),
        ):
            with self.subTest(mismatch=label):
                self.assert_review_or_build_rejected(f"mismatch_{label}", mutator, pattern)

    def test_strict_json_unknown_fields_and_overwrite_are_rejected(self) -> None:
        work = self.workdir("strict_json")
        duplicate = work / "duplicate.json"
        duplicate.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
        failed = self.run_cli("finalize-review", str(duplicate), "--output", str(work / "duplicate-final.json"))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("duplicate json", failed.stderr.lower())

        nonfinite = work / "nonfinite.json"
        nonfinite.write_text('{"schema":NaN}\n', encoding="utf-8")
        failed = self.run_cli("finalize-review", str(nonfinite), "--output", str(work / "nonfinite-final.json"))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("non-standard json", failed.stderr.lower())

        def unknown(review: dict[str, object]) -> None:
            review["gaussian_route"] = "forbidden"

        self.assert_review_or_build_rejected("unknown", unknown, r"unknown field")

        review, plan, _ = self.require_plan("overwrite")
        review_before = review.read_bytes()
        overwrite_draft = self.workdir("overwrite_draft") / "review.json"
        write_json(overwrite_draft, self.review_data())
        failed = self.run_cli("finalize-review", str(overwrite_draft), "--output", str(review))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("overwrite", failed.stderr.lower())
        self.assertEqual(review.read_bytes(), review_before)
        plan_before = plan.read_bytes()
        failed = self.run_cli(
            "build-plan", str(self.local_upstream(plan.parent)["intake"]),
            str(self.local_upstream(plan.parent)["registry"]),
            str(self.local_upstream(plan.parent)["condition"]),
            str(self.local_upstream(plan.parent)["mechanism"]),
            "--review", str(review), "--output", str(plan),
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("overwrite", failed.stderr.lower())
        self.assertEqual(plan.read_bytes(), plan_before)
        index = plan.parent / "study-index.json"
        self.assert_success(self.run_cli("build-index", str(plan), "--output", str(index)))
        index_before = index.read_bytes()
        failed = self.run_cli("build-index", str(plan), "--output", str(index))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("overwrite", failed.stderr.lower())
        self.assertEqual(index.read_bytes(), index_before)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_leaf_and_parent_symlink_bindings_are_rejected(self) -> None:
        review, _, _ = self.require_plan("symlink_source")

        leaf_work = self.workdir("leaf_symlink")
        leaf_paths = self.local_upstream(leaf_work)
        leaf = leaf_work / "review-link.json"
        os.symlink(review, leaf)
        leaf_plan = leaf_work / "plan.json"
        result = self.run_cli(
            "build-plan", str(leaf_paths["intake"]), str(leaf_paths["registry"]),
            str(leaf_paths["condition"]), str(leaf_paths["mechanism"]),
            "--review", str(leaf), "--output", str(leaf_plan),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr.lower())
        self.assertFalse(leaf_plan.exists())

        parent_work = self.workdir("parent_symlink")
        parent_paths = self.local_upstream(parent_work)
        real_parent = parent_work / "real"
        real_parent.mkdir()
        parent_review = real_parent / "review.json"
        parent_review.write_bytes(review.read_bytes())
        linked_parent = parent_work / "linked"
        os.symlink(real_parent, linked_parent)
        parent_plan = parent_work / "plan.json"
        result = self.run_cli(
            "build-plan", str(parent_paths["intake"]), str(parent_paths["registry"]),
            str(parent_paths["condition"]), str(parent_paths["mechanism"]),
            "--review", str(linked_parent / "review.json"), "--output", str(parent_plan),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr.lower())
        self.assertFalse(parent_plan.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_symlinked_output_ancestor_and_dangling_output_links_are_rejected(self) -> None:
        real_parent = self.workdir("output_symlink_real_parent")
        artifact_root = real_parent / "artifacts"
        artifact_root.mkdir()
        review, plan, result = self.build_plan(artifact_root, stem="source")
        self.assert_success(result)

        alias_parent = self.workdir("output_symlink_alias_parent")
        alias = alias_parent / "alias"
        os.symlink(real_parent, alias)
        alias_root = alias / "artifacts"

        escaped_review = alias_root / "escaped-review.json"
        finalized = self.run_cli(
            "finalize-review",
            str(alias_root / "source-review-draft.json"),
            "--output",
            str(escaped_review),
        )
        escaped_plan = alias_root / "escaped-plan.json"
        planned = self.run_cli(
            "build-plan",
            str(alias_root / "intake.json"),
            str(alias_root / "registry.json"),
            str(alias_root / "condition.json"),
            str(alias_root / "mechanism.json"),
            "--review",
            str(alias_root / "source-review.json"),
            "--output",
            str(escaped_plan),
        )
        escaped_index = alias_root / "escaped-index.json"
        indexed = self.run_cli(
            "build-index", str(alias_root / plan.name), "--output", str(escaped_index),
        )
        for label, attempted, target in (
            ("finalize", finalized, escaped_review),
            ("plan", planned, escaped_plan),
            ("index", indexed, escaped_index),
        ):
            with self.subTest(symlinked_output_ancestor=label):
                self.assertNotEqual(attempted.returncode, 0, attempted.stdout)
                self.assertIn("symlink", (attempted.stderr or attempted.stdout).lower())
                self.assertFalse(target.exists())

        dangling_cases: list[tuple[str, subprocess.CompletedProcess[str], Path, Path]] = []
        dangling_review = artifact_root / "dangling-review.json"
        dangling_review_target = artifact_root / "missing-review-target.json"
        os.symlink(dangling_review_target, dangling_review)
        dangling_cases.append((
            "finalize",
            self.run_cli(
                "finalize-review", str(artifact_root / "source-review-draft.json"),
                "--output", str(dangling_review),
            ),
            dangling_review,
            dangling_review_target,
        ))
        dangling_plan = artifact_root / "dangling-plan.json"
        dangling_plan_target = artifact_root / "missing-plan-target.json"
        os.symlink(dangling_plan_target, dangling_plan)
        dangling_cases.append((
            "plan",
            self.run_cli(
                "build-plan",
                str(artifact_root / "intake.json"),
                str(artifact_root / "registry.json"),
                str(artifact_root / "condition.json"),
                str(artifact_root / "mechanism.json"),
                "--review", str(review), "--output", str(dangling_plan),
            ),
            dangling_plan,
            dangling_plan_target,
        ))
        dangling_index = artifact_root / "dangling-index.json"
        dangling_index_target = artifact_root / "missing-index-target.json"
        os.symlink(dangling_index_target, dangling_index)
        dangling_cases.append((
            "index",
            self.run_cli("build-index", str(plan), "--output", str(dangling_index)),
            dangling_index,
            dangling_index_target,
        ))
        for label, attempted, link, target in dangling_cases:
            with self.subTest(dangling_output=label):
                self.assertNotEqual(attempted.returncode, 0, attempted.stdout)
                self.assertTrue(link.is_symlink())
                self.assertFalse(target.exists())

    def test_file_size_hash_payload_drift_and_rehashed_forgery_are_rejected(self) -> None:
        for drift in ("size", "file_hash", "payload"):
            with self.subTest(drift=drift):
                review, plan_path, plan = self.require_plan(f"drift_{drift}")
                if drift == "size":
                    review.write_bytes(review.read_bytes() + b" \n")
                elif drift == "file_hash":
                    data = bytearray(review.read_bytes())
                    position = data.index(b"fixture_calculation_plan")
                    data[position] = ord("g")
                    review.write_bytes(bytes(data))
                else:
                    plan["review_source"]["payload_sha256"] = "0" * 64
                    rehash(plan)
                    plan_path.write_bytes(canonical_bytes(plan))
                checked = self.run_cli("validate-plan", str(plan_path))
                self.assertNotEqual(checked.returncode, 0)
                self.assertRegex(checked.stderr.lower(), r"size|file hash|payload|binding|drift")

        _, forged_plan_path, forged_plan = self.require_plan("forged_plan")
        forged_plan["topological_order"] = list(reversed(forged_plan["topological_order"]))
        rehash(forged_plan)
        forged_plan_path.write_bytes(canonical_bytes(forged_plan))
        checked = self.run_cli("validate-plan", str(forged_plan_path))
        self.assertNotEqual(checked.returncode, 0)
        self.assertRegex(
            checked.stderr.lower(),
            r"topological|normalized|review|recomput|deterministic reconstruction",
        )

        _, plan_path, _ = self.require_plan("forged_index")
        index_path = plan_path.parent / "study-index.json"
        self.assert_success(self.run_cli("build-index", str(plan_path), "--output", str(index_path)))
        index = load_json(index_path)
        index["last_accepted_stage"] = "intake"
        rehash(index)
        index_path.write_bytes(canonical_bytes(index))
        checked = self.run_cli("validate-index", str(index_path))
        self.assertNotEqual(checked.returncode, 0)
        self.assertRegex(checked.stderr.lower(), r"stage|resume|deterministic|recomput|index")

    def test_deep_node_supersession_is_iterative_and_plan_ancestry_is_bounded(self) -> None:
        node_count = 1101

        def deep_node_chain(review: dict[str, object]) -> None:
            template = copy.deepcopy(by_id(review["nodes"], "node_id", "minimum_reactants"))
            nodes: list[dict[str, object]] = []
            supersessions: list[dict[str, object]] = []
            for index in range(node_count):
                node = copy.deepcopy(template)
                node_id = f"deep_minimum_{index:04d}"
                node["node_id"] = node_id
                node["label"] = f"Deep retained minimum {index}"
                node["disposition"] = "superseded" if index < node_count - 1 else "planned"
                nodes.append(node)
                if index:
                    supersessions.append({
                        "supersession_id": f"deep_supersession_{index:04d}",
                        "superseding_node_id": node_id,
                        "superseded_node_ids": [f"deep_minimum_{index - 1:04d}"],
                        "rationale": "Adversarial deep acyclic supersession chain.",
                    })
            review["nodes"] = nodes
            review["alternative_groups"] = []
            review["supersessions"] = supersessions

        _, _, deep_plan = self.require_plan("deep_node_supersession", deep_node_chain)
        self.assertEqual(deep_plan["coverage"]["node_count"], node_count)
        self.assertEqual(len(deep_plan["coverage"]["historical_node_ids"]), node_count - 1)

        work = self.workdir("bounded_plan_ancestry")
        review_path, first_path, built = self.build_plan(work, stem="seed")
        self.assert_success(built)
        first = load_json(first_path)
        base_review = load_json(review_path)
        prior_path = first_path
        prior = first
        maximum_valid_path: Path | None = None
        maximum_valid: dict[str, object] | None = None
        for index in range(MAX_SUPERSEDED_PLAN_DEPTH):
            review = copy.deepcopy(base_review)
            review["superseded_plan_payload_sha256s"] = [prior["payload_sha256"]]
            rehash(review)
            revision_review_path = work / f"revision-{index:03d}-review.json"
            revision_review_path.write_bytes(canonical_bytes(review))
            review_raw = revision_review_path.read_bytes()

            prior_raw = prior_path.read_bytes()
            plan = copy.deepcopy(first)
            plan["review_source"] = {
                "path": revision_review_path.name,
                "sha256": hashlib.sha256(review_raw).hexdigest(),
                "size_bytes": len(review_raw),
                "schema": "gaussian-reaction-calculation-plan-review/1",
                "payload_sha256": review["payload_sha256"],
            }
            plan["superseded_plans"] = [{
                "path": prior_path.name,
                "sha256": hashlib.sha256(prior_raw).hexdigest(),
                "size_bytes": len(prior_raw),
                "schema": "gaussian-reaction-calculation-plan/1",
                "payload_sha256": prior["payload_sha256"],
            }]
            rehash(plan)
            revision_plan_path = work / f"revision-{index:03d}-plan.json"
            revision_plan_path.write_bytes(canonical_bytes(plan))
            prior_path = revision_plan_path
            prior = plan
            if index == MAX_SUPERSEDED_PLAN_DEPTH - 2:
                maximum_valid_path = prior_path
                maximum_valid = prior

        checked = self.run_cli("validate-plan", str(prior_path))
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn(f"exceeds supported depth {MAX_SUPERSEDED_PLAN_DEPTH}", checked.stderr.lower())
        self.assertNotIn("recursionerror", checked.stderr.lower())

        self.assertIsNotNone(maximum_valid_path)
        self.assertIsNotNone(maximum_valid)
        assert maximum_valid_path is not None and maximum_valid is not None
        self.assert_success(self.run_cli("validate-plan", str(maximum_valid_path)))

        def overflowing_revision(value: dict[str, object]) -> None:
            value["superseded_plan_payload_sha256s"] = [maximum_valid["payload_sha256"]]

        _, refused_path, refused = self.build_plan(
            work,
            overflowing_revision,
            superseded_plans=(maximum_valid_path,),
            stem="builder-overflow",
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(f"exceeds supported depth {MAX_SUPERSEDED_PLAN_DEPTH}", refused.stderr.lower())
        self.assertFalse(refused_path.exists())

    def test_superseded_plan_is_exactly_bound_and_visible_in_resume_index(self) -> None:
        work = self.workdir("superseded")
        nested = work / "nested"
        nested.mkdir()
        _, first_path, result = self.build_plan(nested, stem="first")
        self.assert_success(result)
        first = load_json(first_path)

        def revision(review: dict[str, object]) -> None:
            review["superseded_plan_payload_sha256s"] = [first["payload_sha256"]]

        _, second_path, result = self.build_plan(
            nested, revision, superseded_plans=(first_path,), stem="second",
        )
        self.assert_success(result)
        second = load_json(second_path)
        self.assertEqual(len(second["superseded_plans"]), 1)
        self.assertEqual(second["superseded_plans"][0]["payload_sha256"], first["payload_sha256"])
        index_path = second_path.parent / "study-index.json"
        self.assert_success(self.run_cli("build-index", str(second_path), "--output", str(index_path)))
        index = load_json(index_path)
        self.assertEqual(index["superseded_artifacts"], second["superseded_plans"])
        self.assertEqual(index["coverage"], second["coverage"])

        def third_revision(review: dict[str, object]) -> None:
            review["superseded_plan_payload_sha256s"] = [second["payload_sha256"]]

        _, third_path, result = self.build_plan(
            work,
            third_revision,
            superseded_plans=(second_path,),
            stem="third",
        )
        self.assert_success(result)
        third_index_path = work / "third-study-index.json"
        self.assert_success(self.run_cli("build-index", str(third_path), "--output", str(third_index_path)))
        third_index = load_json(third_index_path)
        self.assertEqual(
            {item["payload_sha256"] for item in third_index["superseded_artifacts"]},
            {first["payload_sha256"], second["payload_sha256"]},
        )
        first_entry = next(
            item for item in third_index["superseded_artifacts"]
            if item["payload_sha256"] == first["payload_sha256"]
        )
        self.assertEqual(first_entry["path"], "nested/first-plan.json")
        review_entries = [
            item for item in third_index["artifacts"]
            if item["role"] == "calculation_plan_review" and item["status"] == "current"
        ]
        self.assertEqual(len(review_entries), 1)


if __name__ == "__main__":
    unittest.main()
