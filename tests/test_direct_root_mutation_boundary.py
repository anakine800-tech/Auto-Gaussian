#!/usr/bin/env python3
"""Focused offline tests for the minimal direct-root mutation boundary."""

from __future__ import annotations

import ast
import copy
import inspect
import json
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests.test_direct_root_owner_contract import DirectRootFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_root_mutation_boundary as BOUNDARY  # noqa: E402
import direct_root_owner_contract as ROOT_OWNER  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


class DirectRootMutationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = DirectRootFixture(successor=True)
        self.owner = BOUNDARY.DirectRootMutationBoundaryOwner._for_testing(
            _test_token=BOUNDARY._TEST_TOKEN
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def helper(self, failure_after: str | None = None) -> object:
        return self.owner._synthetic_helper_for_testing(
            failure_after=failure_after,
            _test_token=BOUNDARY._TEST_TOKEN,
        )

    def transaction(self, *, capability: object | None = None, helper: object | None = None) -> object:
        return self.owner.issue_synthetic_transaction_once(
            root_capability=capability or self.fixture.capability(),
            helper=helper or self.helper(),
        )

    def test_exact_successor_chain_runs_only_two_fixed_synthetic_operations(self) -> None:
        capability = self.fixture.capability()
        helper = self.helper()
        transaction = self.transaction(capability=capability, helper=helper)
        binding = transaction.portable_binding()
        authorization = json.loads(capability._authorization_bytes)
        self.assertEqual(binding["profile_schema"], "auto-g16-execution-profile/4")
        self.assertEqual(
            binding["authorization_schema"],
            "auto-g16-execution-authorization/4",
        )
        self.assertFalse(binding["live_ready"])
        self.assertFalse(authorization["live_ready"])
        self.assertFalse(binding["filesystem_authority"])
        self.assertNotIn(self.fixture.profile["declared_allowed_root"], json.dumps(binding))
        document = transaction.consume_and_apply_synthetic_once()
        self.assertEqual(transaction.outcome(), BOUNDARY.COMPLETED)
        self.assertEqual(
            helper.trace(),
            (BOUNDARY.CREATE_PROJECT.kind, BOUNDARY.CREATE_SCRATCH.kind),
        )
        self.assertEqual(
            BOUNDARY.CREATE_PROJECT.kind,
            "create_project_directory_exclusive",
        )
        self.assertEqual(
            document["operations"],
            [operation.document() for operation in BOUNDARY.FIXED_OPERATIONS],
        )
        self.assertEqual(
            document["authority"],
            {
                "synthetic_only": True,
                "schema_valid_is_capability": False,
                "filesystem_authority": False,
                "backend_supported": False,
                "live_ready": False,
                "remote_effect_performed": False,
                "transport_authorized": False,
                "shell_authorized": False,
                "qsub_authorized": False,
                "path_reopen_allowed": False,
                "automatic_retry": False,
            },
        )

    def test_check_to_use_passes_the_same_opaque_handles_and_no_path(self) -> None:
        capability = self.fixture.capability()
        expected_handles = capability._descriptor_handles
        helper = self.helper()
        transaction = self.transaction(capability=capability, helper=helper)
        transaction.consume_and_apply_synthetic_once()
        self.assertIs(expected_handles, capability._descriptor_set._opaque_handles)
        for operation in BOUNDARY.FIXED_OPERATIONS:
            self.assertFalse(any("/" in item or "\\" in item for item in operation.relative_components))

    def test_concurrent_consumers_have_one_winner(self) -> None:
        helper = self.helper()
        transaction = self.transaction(helper=helper)

        def consume(_: int) -> object:
            try:
                return transaction.consume_and_apply_synthetic_once()
            except BOUNDARY.DirectRootMutationBoundaryError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume, range(16)))
        self.assertEqual(
            sum(type(value) is dict for value in results),
            1,
        )
        self.assertEqual(len(helper.trace()), 2)

    def test_helper_failure_is_terminal_uncertain_and_never_retried(self) -> None:
        helper = self.helper(BOUNDARY.CREATE_PROJECT.kind)
        transaction = self.transaction(helper=helper)
        with self.assertRaisesRegex(RuntimeError, "synthetic fixed-operation failure"):
            transaction.consume_and_apply_synthetic_once()
        self.assertEqual(
            transaction.outcome(),
            BOUNDARY.EFFECT_STARTED_OUTCOME_UNCERTAIN,
        )
        self.assertEqual(helper.trace(), (BOUNDARY.CREATE_PROJECT.kind,))
        with self.assertRaisesRegex(
            BOUNDARY.DirectRootMutationBoundaryError,
            "already consumed or terminal",
        ):
            transaction.consume_and_apply_synthetic_once()

    def test_json_hash_and_schema_valid_result_never_issue_capability(self) -> None:
        document = self.transaction().consume_and_apply_synthetic_once()
        BOUNDARY.validate_synthetic_mutation_result(document)
        for constructor in (
            ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
            BOUNDARY.SingleUseDirectRootSyntheticMutationTransaction,
        ):
            with self.subTest(constructor=constructor.__name__):
                with self.assertRaises(TypeError):
                    constructor(document)
        owner = BOUNDARY.DirectRootMutationBoundaryOwner._for_testing(
            _test_token=BOUNDARY._TEST_TOKEN
        )
        helper = owner._synthetic_helper_for_testing(_test_token=BOUNDARY._TEST_TOKEN)
        with self.assertRaises(BOUNDARY.DirectRootMutationBoundaryError):
            owner.issue_synthetic_transaction_once(root_capability=document, helper=helper)

    def test_result_fixed_booleans_reject_integer_lookalikes_after_rehash(self) -> None:
        baseline = self.transaction().consume_and_apply_synthetic_once()
        BOUNDARY.validate_synthetic_mutation_result(baseline)
        for field, expected in BOUNDARY.RESULT_AUTHORITY.items():
            with self.subTest(authority=field):
                hostile = copy.deepcopy(baseline)
                hostile["authority"][field] = int(expected)
                hostile = BOUNDARY._finalize(hostile, "result_payload_sha256")
                with self.assertRaisesRegex(
                    BOUNDARY.DirectRootMutationBoundaryError,
                    "authority differs",
                ):
                    BOUNDARY.validate_synthetic_mutation_result(hostile)

        for index, operation in enumerate(baseline["operations"]):
            for field, expected in operation.items():
                if type(expected) is not bool:
                    continue
                with self.subTest(operation=index, field=field):
                    hostile = copy.deepcopy(baseline)
                    hostile["operations"][index][field] = int(expected)
                    hostile = BOUNDARY._finalize(hostile, "result_payload_sha256")
                    with self.assertRaisesRegex(
                        BOUNDARY.DirectRootMutationBoundaryError,
                        "fixed operations differ",
                    ):
                        BOUNDARY.validate_synthetic_mutation_result(hostile)

    def test_result_closed_nested_container_types_and_order_are_exact(self) -> None:
        baseline = self.transaction().consume_and_apply_synthetic_once()
        candidates = []
        hostile = copy.deepcopy(baseline)
        hostile["authority"] = list(hostile["authority"].items())
        candidates.append(("authority-list", hostile))
        hostile = copy.deepcopy(baseline)
        hostile["authority"]["unexpected"] = False
        candidates.append(("authority-extra", hostile))
        hostile = copy.deepcopy(baseline)
        hostile["authority"].pop("live_ready")
        candidates.append(("authority-missing", hostile))
        hostile = copy.deepcopy(baseline)
        hostile["operations"] = tuple(hostile["operations"])
        candidates.append(("operations-tuple", hostile))
        hostile = copy.deepcopy(baseline)
        hostile["operations"] = list(reversed(hostile["operations"]))
        candidates.append(("operations-reordered", hostile))
        hostile = copy.deepcopy(baseline)
        hostile["operations"][0]["relative_components"] = tuple(
            hostile["operations"][0]["relative_components"]
        )
        candidates.append(("components-tuple", hostile))
        hostile = copy.deepcopy(baseline)
        hostile["operations"][0]["unexpected"] = False
        candidates.append(("operation-extra", hostile))
        hostile = copy.deepcopy(baseline)
        hostile["operations"][0].pop("create_mode")
        candidates.append(("operation-missing", hostile))
        for label, hostile in candidates:
            with self.subTest(label=label):
                hostile = BOUNDARY._finalize(hostile, "result_payload_sha256")
                with self.assertRaises(BOUNDARY.DirectRootMutationBoundaryError):
                    BOUNDARY.validate_synthetic_mutation_result(hostile)

    def test_old_unknown_missing_and_fallback_routes_reject(self) -> None:
        rejected = (
            {},
            {"schema": "auto-g16-execution-profile/1", "backend_kind": "direct_ssh_pbs"},
            {"schema": "auto-g16-execution-profile/2", "backend_kind": "legacy_rtwin_pbs"},
            {"schema": "auto-g16-execution-authorization/1"},
            {"schema": "auto-g16-execution-authorization/2"},
            {"schema": "auto-g16-execution-profile/4"},
            {"schema": "unknown"},
            {"profile": self.fixture.profile, "fallback": "v3"},
        )
        helper = self.helper()
        for candidate in rejected:
            with self.subTest(candidate=candidate):
                with self.assertRaises(BOUNDARY.DirectRootMutationBoundaryError):
                    self.owner.issue_synthetic_transaction_once(
                        root_capability=candidate,
                        helper=helper,
                    )
        source = (SCRIPTS / "direct_root_mutation_boundary.py").read_text(encoding="utf-8")
        for forbidden in ("backfill", "rehash", "migrate_execution", "build_execution_profile"):
            self.assertNotIn(forbidden, source)

    def test_valid_historical_chain_is_replay_only_before_w4(self) -> None:
        legacy = DirectRootFixture()
        helper = self.helper()
        with self.assertRaisesRegex(
            BOUNDARY.DirectRootMutationBoundaryError, "closed successor"
        ):
            self.owner.issue_synthetic_transaction_once(
                root_capability=legacy.capability(), helper=helper,
            )
        self.assertEqual(helper.trace(), ())

    def test_cli_environment_and_root_override_have_no_route(self) -> None:
        signature = inspect.signature(
            BOUNDARY.DirectRootMutationBoundaryOwner.issue_synthetic_transaction_once
        )
        self.assertEqual(tuple(signature.parameters), ("self", "root_capability", "helper"))
        capability = self.fixture.capability()
        helper = self.helper()
        with mock.patch.dict(
            os.environ,
            {
                "AUTO_G16_ROOT": "/tmp/override",
                "AUTO_G16_DIRECT_ROOT": "/tmp/override",
                "AUTO_G16_BACKEND": "legacy_rtwin_pbs",
            },
            clear=False,
        ):
            transaction = self.owner.issue_synthetic_transaction_once(
                root_capability=capability,
                helper=helper,
            )
        self.assertNotIn("/tmp/override", json.dumps(transaction.portable_binding()))
        with self.assertRaises(TypeError):
            self.owner.issue_synthetic_transaction_once(
                root_capability=capability,
                helper=helper,
                root="/tmp/override",
            )

    def test_no_runtime_transport_legacy_or_existing_replay_owner_is_combined(self) -> None:
        tree = ast.parse(
            (SCRIPTS / "direct_root_mutation_boundary.py").read_text(encoding="utf-8")
        )
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "argparse",
            "subprocess",
            "socket",
            "paramiko",
            "platform_contracts",
            "execution_authorization",
            "legacy_rtwin_pbs",
            "legacy_root_authority_contract",
            "resource_effect_time_replay_owner",
            "live_approval_effect_time_replay",
            "protected_job_runtime_coordinator",
            "protected_production_factory_consumer",
        ):
            self.assertNotIn(forbidden, imports)

    def test_package_is_additive_and_legacy_root_remains_fixed(self) -> None:
        package = SKILL_PACKAGE.package_files_with_supplements(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            package[Path("scripts/direct_root_mutation_boundary.py")],
            SCRIPTS / "direct_root_mutation_boundary.py",
        )
        self.assertEqual(
            package[Path("references/direct-root-mutation-boundary.md")],
            ROOT / "docs/v2.7-direct-root-mutation-boundary.md",
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-rtwin-pbs/scripts/direct_root_mutation_boundary.py").exists()
        )
        legacy = (ROOT / "scripts/legacy_root_authority_contract.py").read_text(encoding="utf-8")
        self.assertIn('FIXED_REMOTE_ROOT = "/home/user100/SDL"', legacy)


if __name__ == "__main__":
    unittest.main()
