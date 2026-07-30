#!/usr/bin/env python3
"""Offline hostile tests for the legacy descriptor-relative mutation capability."""

from __future__ import annotations

import copy
import pickle
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from tests import test_protected_production_factory_consumer as FACTORY_SUPPORT
import legacy_root_authority_contract as ROOT_AUTHORITY
import protected_production_factory_consumer as FACTORY


class LegacyDescriptorMutationCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.support = (
            FACTORY_SUPPORT.ProtectedProductionFactoryConsumerTests("runTest")
        )
        self.support.setUp()
        self.addCleanup(self.support.doCleanups)
        self.result = self.support.consume(self.support.make_port())
        self.owner = ROOT_AUTHORITY.LegacyRootAuthorityContractOwner._for_testing(
            clock=lambda: None,
            nonce_source=lambda: "",
            _test_token=ROOT_AUTHORITY._TEST_TOKEN,
        )

    def capability(self, recorder: object, outcomes: object | None = None) -> object:
        operation = self.owner._mutation_operation_for_testing(
            recorder,
            outcomes,
            _test_token=ROOT_AUTHORITY._TEST_TOKEN,
        )
        return self.owner.issue_descriptor_relative_mutation_capability_once(
            production_factory_result=self.result,
            operation=operation,
        )

    def test_exact_factory_coordinator_and_descriptor_objects_are_authority(self) -> None:
        calls = []
        capability = self.capability(
            lambda handles, relative: calls.append((handles, relative)) or "ok"
        )
        binding = capability.portable_binding()
        self.assertEqual(binding["fixed_root"], "/home/user100/SDL")
        self.assertEqual(
            binding["production_factory_result_sha256"],
            self.result.document()["payload_sha256"],
        )
        self.assertEqual(capability.consume_and_invoke_once(), "ok")
        handles, relative = calls[0]
        self.assertTrue(all(type(item) is object for item in handles))
        self.assertEqual(relative, ("project", "scratch"))
        self.assertNotIn("/home/user100/SDL", relative)

    def test_atomic_single_winner(self) -> None:
        calls = []
        lock = threading.Lock()

        def recorder(*args: object) -> str:
            with lock:
                calls.append(args)
            return "done"

        capability = self.capability(recorder)

        def invoke(_: int) -> object:
            try:
                return capability.consume_and_invoke_once()
            except ROOT_AUTHORITY.LegacyRootAuthorityError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(invoke, range(16)))
        self.assertEqual(results.count("done"), 1)
        self.assertEqual(len(calls), 1)

    def test_exception_records_durable_uncertainty_and_never_retries(self) -> None:
        effects = []
        outcomes = []

        def fail(*args: object) -> None:
            effects.append(args)
            raise RuntimeError("synthetic outcome unavailable")

        capability = self.capability(fail, outcomes.append)
        with self.assertRaisesRegex(RuntimeError, "outcome unavailable"):
            capability.consume_and_invoke_once()
        self.assertEqual(outcomes, ["effect_started_outcome_uncertain"])
        self.assertEqual(capability.outcome(), "effect_started_outcome_uncertain")
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "already consumed or uncertain",
        ):
            capability.consume_and_invoke_once()
        self.assertEqual(len(effects), 1)

    def test_copy_pickle_forgery_replacement_and_reload_fail_closed(self) -> None:
        capability = self.capability(lambda *_: "ok")
        for copier in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaises(TypeError):
                copier(capability)
        with self.assertRaises(TypeError):
            ROOT_AUTHORITY.SingleUseLegacyDescriptorRelativeMutationCapability()
        state = ROOT_AUTHORITY._mutation_state(capability)
        state.operation_method = lambda *_: None
        with self.assertRaises(ROOT_AUTHORITY.LegacyRootAuthorityError):
            capability.consume_and_invoke_once()
        effects = []
        capability = self.capability(lambda *_: effects.append("effect"))
        canonical = sys.modules[FACTORY.__name__]
        sys.modules[FACTORY.__name__] = mock.Mock()
        try:
            with self.assertRaises(ROOT_AUTHORITY.LegacyRootAuthorityError):
                capability.consume_and_invoke_once()
        finally:
            sys.modules[FACTORY.__name__] = canonical
        self.assertEqual(effects, [])

    def test_foreign_factory_result_and_descriptor_identity_drift_are_zero_effect(self) -> None:
        effects = []
        capability = self.capability(lambda *_: effects.append("effect"))
        state = ROOT_AUTHORITY._mutation_state(capability)
        state.descriptor_handles = (object(), object(), object())
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "identity drifted",
        ):
            capability.consume_and_invoke_once()
        self.assertEqual(effects, [])
        capability = self.capability(lambda *_: effects.append("foreign-effect"))
        object.__setattr__(capability, "_factory_result", object())
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "snapshot differs",
        ):
            capability.consume_and_invoke_once()
        canonical = sys.modules.pop(FACTORY.__name__)
        try:
            with self.assertRaisesRegex(
                ROOT_AUTHORITY.LegacyRootAuthorityError,
                "module must load first",
            ):
                self.capability(lambda *_: effects.append("import-effect"))
        finally:
            sys.modules[FACTORY.__name__] = canonical
        self.assertEqual(effects, [])


if __name__ == "__main__":
    unittest.main()
