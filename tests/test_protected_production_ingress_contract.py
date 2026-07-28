#!/usr/bin/env python3
"""Offline tests for the protected production-ingress successor."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
import textwrap
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEMP_PARENT == ROOT or ROOT in TEMP_PARENT.parents:
    raise RuntimeError("production-ingress tests require a system temporary root")
os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(
    TEMP_PARENT / "auto-g16-production-ingress-placeholder-absent.json"
)
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import legacy_rtwin_pbs as LEGACY  # noqa: E402
import execution_facade as FACADE  # noqa: E402
from tests import test_protected_owner_consumer_contract as OWNER_SUPPORT  # noqa: E402
from tests.test_protected_runtime_state_contract import (  # noqa: E402
    RuntimeStateFixture,
)
import protected_owner_consumer_contract as CONSUMER  # noqa: E402
import protected_production_ingress_contract as INGRESS  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


PUBLIC_INTEGER_FIELDS = (
    "binding_order",
    "upload_timeout_seconds",
    "upload_hash_timeout_seconds",
)


def set_public_integer(
    document: dict[str, object],
    field: str,
    value: object,
) -> None:
    plan = document["legacy_factory_port"]["plan_inputs"]
    if field == "binding_order":
        plan["expected_bindings"][0]["order"] = value
    else:
        plan[field] = value


def get_public_integer(
    document: dict[str, object],
    field: str,
) -> object:
    plan = document["legacy_factory_port"]["plan_inputs"]
    if field == "binding_order":
        return plan["expected_bindings"][0]["order"]
    return plan[field]


def reclose_public_document(
    document: dict[str, object],
) -> dict[str, object]:
    port = document["legacy_factory_port"]
    plan = port["plan_inputs"]
    port["plan_inputs_sha256"] = INGRESS.digest(plan)
    document["contract_payload_sha256"] = INGRESS._payload_sha256(document)
    predecessor = document["predecessor"]
    document["contract_id"] = INGRESS._contract_id(
        predecessor_contract_id=predecessor["contract_id"],
        uncertain_receipt_payload_sha256=predecessor[
            "uncertain_receipt_payload_sha256"
        ],
        plan_inputs_sha256=port["plan_inputs_sha256"],
        contract_payload_sha256=document["contract_payload_sha256"],
    )
    return document


class ProtectedProductionIngressContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-protected-production-ingress-",
            dir=TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = RuntimeStateFixture(self.root)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def predecessor(
        self,
    ) -> CONSUMER.SealedProtectedOwnerConsumerContract:
        runtime = self.fixture.owner().seal(self.fixture.handoff())
        return (
            CONSUMER.ProtectedOwnerConsumerContractOwner.production()
            .prepare_once(runtime)
        )

    def sealed(
        self,
    ) -> INGRESS.SealedProtectedProductionIngressCapability:
        return (
            INGRESS.ProtectedProductionIngressContractOwner.production()
            .seal_once(self.predecessor())
        )

    def foreign_identical_ingress_module(self) -> object:
        canonical = sys.modules[INGRESS.MODULE_NAME]
        consumer_module = INGRESS._CONSUMER_BINDING.module
        registration = INGRESS._REGISTRATION_ATTRIBUTE
        registered = getattr(consumer_module, registration)
        source = ROOT / "scripts/protected_production_ingress_contract.py"
        spec = importlib.util.spec_from_file_location(
            INGRESS.MODULE_NAME,
            source,
        )
        assert spec is not None and spec.loader is not None
        foreign = importlib.util.module_from_spec(spec)
        delattr(consumer_module, registration)
        sys.modules[INGRESS.MODULE_NAME] = foreign
        try:
            spec.loader.exec_module(foreign)
        finally:
            sys.modules[INGRESS.MODULE_NAME] = canonical
            setattr(consumer_module, registration, registered)
        return foreign

    def test_exact_predecessor_claim_and_effect_free_factory_port(self) -> None:
        predecessor = self.predecessor()
        runtime = predecessor.runtime_state
        before_receipts = [
            receipt.document() for receipt in runtime._journal.receipts
        ]
        before_bundle = {
            path.name: path.read_bytes()
            for path in predecessor.upload_path.iterdir()
        }
        before_plan_bindings = len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS)
        before_owner_bindings = len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS)
        with (
            mock.patch.object(LEGACY, "run") as runner,
            mock.patch.object(
                LEGACY.LegacyTransportAdapter,
                "invoke_reserved_once",
            ) as adapter,
            mock.patch.object(
                type(runtime),
                "consume_for_effect_once",
                autospec=True,
            ) as runtime_consume,
            mock.patch.object(
                type(runtime),
                "prepare_effect_boundary_once",
                autospec=True,
            ) as runtime_boundary,
        ):
            sealed = (
                INGRESS.ProtectedProductionIngressContractOwner.production()
                .seal_once(predecessor)
            )
            port = sealed.claim_legacy_factory_port_once()
        runner.assert_not_called()
        adapter.assert_not_called()
        runtime_consume.assert_not_called()
        runtime_boundary.assert_not_called()
        self.assertEqual(
            before_receipts,
            [receipt.document() for receipt in runtime._journal.receipts],
        )
        self.assertEqual(
            before_bundle,
            {
                path.name: path.read_bytes()
                for path in predecessor.upload_path.iterdir()
            },
        )
        self.assertEqual(
            len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS),
            before_plan_bindings,
        )
        self.assertEqual(
            len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS),
            before_owner_bindings,
        )
        document = sealed.document()
        self.assertFalse(
            document["production_ingress"]["production_submit_wired"]
        )
        self.assertTrue(
            document["legacy_factory_port"][
                "current_factory_requires_cli_transaction"
            ]
        )
        for field in (
            "current_factory_accepts_port",
            "factory_invoked",
            "effect_plan_created",
            "raw_effect_owner_created",
        ):
            self.assertFalse(document["legacy_factory_port"][field])
        self.assertEqual(
            tuple(document["legacy_factory_port"]["required_fields"]),
            INGRESS.PLAN_FIELDS,
        )
        self.assertEqual(
            tuple(document["legacy_factory_port"]["effect_steps"]),
            INGRESS.EFFECT_STEPS,
        )
        self.assertEqual(
            port.files,
            tuple(str(path) for path in predecessor._plan_values["files"]),
        )
        sealed.assert_current()
        port.assert_owner_sealed()

    def test_exact_call_chain_and_owner_source_bindings(self) -> None:
        sealed = self.sealed()
        document = sealed.document()
        self.assertEqual(
            document["call_chain"]["required_order"],
            list(INGRESS.CALL_CHAIN),
        )
        self.assertEqual(
            document["call_chain"]["remaining_gate"],
            "exact_legacy_internal_port_consumer_and_production_wiring",
        )
        bindings = document["owner_bindings"]
        self.assertEqual(
            bindings["owner_consumer_source_sha256"],
            hashlib.sha256(
                (
                    ROOT / "scripts/protected_owner_consumer_contract.py"
                ).read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            bindings["facade_source_sha256"],
            hashlib.sha256(
                (
                    SKILL_SCRIPTS / "execution_facade.py"
                ).read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            bindings["legacy_source_sha256"],
            hashlib.sha256(
                (
                    SKILL_SCRIPTS / "legacy_rtwin_pbs.py"
                ).read_bytes()
            ).hexdigest(),
        )

    def test_copy_pickle_single_use_and_deterministic_concurrency(self) -> None:
        sealed = self.sealed()
        barrier = threading.Barrier(8)

        def claim(_: int) -> object:
            barrier.wait()
            try:
                return sealed.claim_legacy_factory_port_once()
            except INGRESS.ProtectedProductionIngressError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(claim, range(8)))
        self.assertEqual(sum(item is not None for item in claims), 1)
        port = next(item for item in claims if item is not None)
        for value in (sealed, port):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    copy.copy(value)
                with self.assertRaises(TypeError):
                    copy.deepcopy(value)
                with self.assertRaises(TypeError):
                    pickle.dumps(value)

        other_root = self.root / "owner-concurrency"
        other_root.mkdir()
        other_fixture = RuntimeStateFixture(other_root)
        try:
            runtime = other_fixture.owner().seal(other_fixture.handoff())
            predecessor = (
                CONSUMER.ProtectedOwnerConsumerContractOwner.production()
                .prepare_once(runtime)
            )
            owner = (
                INGRESS.ProtectedProductionIngressContractOwner.production()
            )
            owner_barrier = threading.Barrier(6)

            def seal(_: int) -> object:
                owner_barrier.wait()
                try:
                    return owner.seal_once(predecessor)
                except INGRESS.ProtectedProductionIngressError:
                    return None

            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(seal, range(6)))
            self.assertEqual(sum(item is not None for item in results), 1)
        finally:
            other_fixture.close()

    def test_snapshot_isolation_nested_mutation_and_equality_hooks(self) -> None:
        sealed = self.sealed()
        original = sealed.document()
        changed_copy = sealed.document()
        changed_copy["legacy_factory_port"]["plan_inputs"][
            "expected_bindings"
        ][0]["sha256"] = "f" * 64
        self.assertEqual(sealed.document(), original)
        sealed.assert_current()

        port = sealed.claim_legacy_factory_port_once()
        original_project = port.project
        object.__setattr__(port, "project", "forged")
        with self.assertRaises(INGRESS.ProtectedProductionIngressError):
            port.assert_owner_sealed()
        object.__setattr__(port, "project", original_project)
        port.assert_owner_sealed()

        class Hostile(dict):
            def __eq__(self, other: object) -> bool:
                raise AssertionError("hostile equality must not run")

        with self.assertRaises(INGRESS.ProtectedProductionIngressError):
            INGRESS.validate_protected_production_ingress_contract(
                Hostile(original)
            )

    def test_fixed_boolean_zero_one_and_semantic_splices_fail_closed(self) -> None:
        document = self.sealed().document()
        boolean_maps = ("validation", "scope", "policy", "threat_model")
        for mapping in boolean_maps:
            for field in document[mapping]:
                for replacement in (0, 1):
                    changed = copy.deepcopy(document)
                    changed[mapping][field] = replacement
                    with self.subTest(
                        mapping=mapping,
                        field=field,
                        replacement=replacement,
                    ):
                        with self.assertRaises(
                            INGRESS.ProtectedProductionIngressError
                        ):
                            INGRESS.validate_protected_production_ingress_contract(
                                changed
                            )
        cases = []
        for field in (
            "contract_id",
            "intent_file_sha256",
            "checksum_file_sha256",
            "expected_bindings_sha256",
        ):
            changed = copy.deepcopy(document)
            if field == "contract_id":
                changed["predecessor"][field] = (
                    "protected-owner-consumer-" + "f" * 64
                )
            else:
                changed["predecessor"][field] = "f" * 64
            changed["contract_payload_sha256"] = INGRESS._payload_sha256(
                changed
            )
            cases.append(changed)
        changed = copy.deepcopy(document)
        changed["legacy_factory_port"]["plan_inputs"][
            "expected_bindings"
        ][0]["sha256"] = "f" * 64
        changed["legacy_factory_port"]["plan_inputs_sha256"] = INGRESS.digest(
            changed["legacy_factory_port"]["plan_inputs"]
        )
        changed["contract_payload_sha256"] = INGRESS._payload_sha256(changed)
        cases.append(changed)
        for changed in cases:
            with self.assertRaises(INGRESS.ProtectedProductionIngressError):
                INGRESS.validate_protected_production_ingress_contract(changed)

    def test_public_integer_normalization_and_rejection_matrix(self) -> None:
        original = self.sealed().document()
        for field in PUBLIC_INTEGER_FIELDS:
            with self.subTest(field=field, representation="exact-int"):
                normalized = (
                    INGRESS.validate_protected_production_ingress_contract(
                        copy.deepcopy(original)
                    )
                )
                self.assertEqual(normalized, original)
                self.assertIs(type(get_public_integer(normalized, field)), int)

            integral = copy.deepcopy(original)
            set_public_integer(
                integral,
                field,
                float(get_public_integer(integral, field)),
            )
            with self.subTest(field=field, representation="canonical-hash"):
                normalized = (
                    INGRESS.validate_protected_production_ingress_contract(
                        integral
                    )
                )
                self.assertEqual(normalized, original)
                self.assertIs(type(get_public_integer(normalized, field)), int)

            raw_closed = reclose_public_document(copy.deepcopy(integral))
            with self.subTest(field=field, representation="raw-hash"):
                normalized = (
                    INGRESS.validate_protected_production_ingress_contract(
                        raw_closed
                    )
                )
                self.assertEqual(normalized, original)
                self.assertIs(type(get_public_integer(normalized, field)), int)

            hybrid_payload = copy.deepcopy(raw_closed)
            hybrid_payload["contract_payload_sha256"] = original[
                "contract_payload_sha256"
            ]
            hybrid_payload["contract_id"] = original["contract_id"]
            with self.subTest(field=field, representation="hybrid-payload"):
                with self.assertRaises(
                    INGRESS.ProtectedProductionIngressError
                ):
                    INGRESS.validate_protected_production_ingress_contract(
                        hybrid_payload
                    )

            hybrid_id = copy.deepcopy(raw_closed)
            hybrid_id["contract_id"] = original["contract_id"]
            with self.subTest(field=field, representation="hybrid-id"):
                with self.assertRaises(
                    INGRESS.ProtectedProductionIngressError
                ):
                    INGRESS.validate_protected_production_ingress_contract(
                        hybrid_id
                    )

            for label, replacement in (
                ("bool", True),
                ("fractional", 1.5),
                ("zero", 0),
                ("negative", -1),
                ("nan", float("nan")),
                ("positive-infinity", float("inf")),
                ("negative-infinity", float("-inf")),
            ):
                changed = copy.deepcopy(original)
                set_public_integer(changed, field, replacement)
                if label not in {
                    "nan",
                    "positive-infinity",
                    "negative-infinity",
                }:
                    reclose_public_document(changed)
                with self.subTest(
                    field=field,
                    representation=label,
                ):
                    with self.assertRaises(
                        INGRESS.ProtectedProductionIngressError
                    ):
                        (
                            INGRESS
                            .validate_protected_production_ingress_contract(
                                changed
                            )
                        )

    def test_cache_class_callable_and_foreign_identical_reject_before_claim(
        self,
    ) -> None:
        predecessor = self.predecessor()
        before_claimed = predecessor._claimed
        owner = INGRESS.ProtectedProductionIngressContractOwner.production()
        canonical = sys.modules[INGRESS.MODULE_NAME]
        foreign = self.foreign_identical_ingress_module()
        self.assertIsNot(
            foreign.ProtectedProductionIngressContractOwner,
            INGRESS.ProtectedProductionIngressContractOwner,
        )
        sys.modules[INGRESS.MODULE_NAME] = foreign
        try:
            with self.assertRaises(INGRESS.ProtectedProductionIngressError):
                owner.seal_once(predecessor)
        finally:
            sys.modules[INGRESS.MODULE_NAME] = canonical
        self.assertEqual(predecessor._claimed, before_claimed)
        self.assertFalse(owner._used)

        replacements = (
            (INGRESS._FACADE_BINDING.adapter_type, "_submit_new"),
            (LEGACY, "_legacy_effect_plan_from_transaction"),
            (CONSUMER, "ProtectedLegacyEffectPlanInputs"),
            (INGRESS, "ProtectedLegacyEffectPlanFactoryPort"),
        )
        for target, attribute in replacements:
            candidate = (
                INGRESS.ProtectedProductionIngressContractOwner.production()
            )
            exact = getattr(target, attribute)
            setattr(target, attribute, mock.Mock())
            try:
                with self.assertRaises(
                    INGRESS.ProtectedProductionIngressError
                ):
                    candidate.seal_once(predecessor)
            finally:
                setattr(target, attribute, exact)
            self.assertEqual(predecessor._claimed, before_claimed)
            self.assertFalse(candidate._used)

    def test_wrong_import_order_and_foreign_predecessor_type_rejected(self) -> None:
        source = ROOT / "scripts/protected_production_ingress_contract.py"
        spec = importlib.util.spec_from_file_location(
            "foreign_protected_production_ingress_contract",
            source,
        )
        assert spec is not None and spec.loader is not None
        foreign = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = foreign
        try:
            with self.assertRaises(ImportError):
                spec.loader.exec_module(foreign)
        finally:
            sys.modules.pop(spec.name, None)

        predecessor = self.predecessor()
        foreign_consumer = (
            OWNER_SUPPORT.ProtectedOwnerConsumerContractTests
            .foreign_identical_consumer_module(self)
        )
        forged = object.__new__(
            foreign_consumer.SealedProtectedOwnerConsumerContract
        )
        owner = INGRESS.ProtectedProductionIngressContractOwner.production()
        with self.assertRaises(TypeError):
            owner.seal_once(forged)
        self.assertFalse(predecessor._claimed)
        self.assertFalse(owner._used)

    def test_source_contains_no_factory_adapter_runner_or_write_call(self) -> None:
        source_path = ROOT / "scripts/protected_production_ingress_contract.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "legacy_rtwin_pbs",
            "execution_facade",
            "subprocess",
            "socket",
        ):
            self.assertNotIn(forbidden, imported)
        for forbidden in (
            "_legacy_effect_plan_from_transaction(",
            "_legacy_raw_effect_owner_from_plan(",
            "invoke_reserved_once(",
            "consume_for_effect_once(",
            "prepare_effect_boundary_once(",
            "write_bytes(",
            "write_text(",
            "qsub(",
            "qstat(",
            "qdel(",
        ):
            self.assertNotIn(forbidden, source)

    def test_schema_valid_document_is_not_owner_sealed(self) -> None:
        document = self.sealed().document()
        validated = (
            INGRESS.validate_protected_production_ingress_contract(document)
        )
        self.assertEqual(validated, document)
        with self.assertRaises(TypeError):
            INGRESS.SealedProtectedProductionIngressCapability()
        with self.assertRaises(TypeError):
            INGRESS.ProtectedLegacyEffectPlanFactoryPort()

    def test_frozen_predecessors_named_package_and_git_free_relocation(
        self,
    ) -> None:
        fixture = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/"
                "protected_production_ingress_contract.json"
            ).read_text(encoding="utf-8")
        )
        for relative, expected in fixture["frozen_predecessors"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                expected,
                relative,
            )
        for relative, binding in fixture["successor_files"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                binding["sha256"],
                relative,
            )
        for relative, expected in fixture["new_files"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                expected,
                relative,
            )
        package = json.loads(
            (
                ROOT / "skills/auto-g16-rtwin-pbs/deployment-package.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(
            "scripts/protected_production_ingress_contract.py",
            {item["source"] for item in package["include"]},
        )
        installed = self.root / "installed-auto-g16-rtwin-pbs"
        installed.mkdir()
        for relative, source in SKILL_PACKAGE.package_files(
            ROOT,
            "auto-g16-rtwin-pbs",
        ).items():
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.assertFalse((installed / ".git").exists())
        script = textwrap.dedent(
            f"""
            import json
            import sys
            from pathlib import Path

            installed = Path({str(installed)!r})
            sys.path.insert(0, str(installed / "scripts"))
            wrong_order_rejected = False
            try:
                import protected_production_ingress_contract
            except ImportError:
                wrong_order_rejected = True
            else:
                raise AssertionError("production ingress wrong order accepted")

            import legacy_rtwin_pbs
            import execution_facade
            import protected_lifecycle_contract
            import protected_local_materialization
            import protected_legacy_effect_handoff
            import protected_runtime_state_contract
            import protected_owner_consumer_contract
            import protected_production_ingress_contract as ingress

            class UntouchedPredecessor:
                def __init__(self):
                    self.touched = False

                def __getattribute__(self, name):
                    if name != "touched":
                        object.__setattr__(self, "touched", True)
                        raise AssertionError("predecessor must remain untouched")
                    return object.__getattribute__(self, name)

            predecessor = UntouchedPredecessor()
            owner = ingress.ProtectedProductionIngressContractOwner.production()
            source_path = Path(ingress.__file__).resolve()
            source_raw = source_path.read_bytes()
            source_path.write_bytes(source_raw + b"\\n")
            try:
                owner.seal_once(predecessor)
            except ingress.ProtectedProductionIngressError:
                source_drift_rejected = True
            else:
                source_drift_rejected = False
            finally:
                source_path.write_bytes(source_raw)

            print(json.dumps({{
                "wrong_order_rejected": wrong_order_rejected,
                "source_drift_rejected": source_drift_rejected,
                "source_drift_zero_claim": (
                    not predecessor.touched and not owner._used
                ),
                "consumer_bound": (
                    ingress._CONSUMER_BINDING.module
                    is protected_owner_consumer_contract
                ),
                "facade_bound": (
                    ingress._FACADE_BINDING.module is execution_facade
                ),
                "legacy_bound": (
                    ingress._LEGACY_BINDING.module is legacy_rtwin_pbs
                ),
            }}))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=installed,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "AUTO_G16_RUNTIME_CONFIG": str(
                    TEMP_PARENT
                    / "auto-g16-production-ingress-installed-placeholder.json"
                ),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["wrong_order_rejected"])
        self.assertTrue(output["source_drift_rejected"])
        self.assertTrue(output["source_drift_zero_claim"])
        self.assertTrue(output["consumer_bound"])
        self.assertTrue(output["facade_bound"])
        self.assertTrue(output["legacy_bound"])


if __name__ == "__main__":
    unittest.main()
