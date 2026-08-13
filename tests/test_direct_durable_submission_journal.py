#!/usr/bin/env python3
"""Hostile offline tests for the direct durable submission journal owner."""

from __future__ import annotations

import ast
import copy
import gc
import hashlib
import importlib
import importlib.util
import json
import multiprocessing
import os
import pickle
import sys
import tempfile
import threading
import unittest
import weakref
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.test_direct_root_owner_contract import ATTEMPT, PROJECT, TASK, DirectRootFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_root_mutation_boundary as ROOT_BOUNDARY  # noqa: E402
import direct_root_owner_contract as ROOT_OWNER  # noqa: E402
import direct_ssh_pbs_offline as DIRECT  # noqa: E402
import direct_durable_submission_journal as JOURNAL  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


PAYLOAD = b"%nprocshared=8\n%mem=12GB\n# synthetic durable journal\n\n"


def _race_worker(local_state_dir: str, binding_bytes: bytes, start: multiprocessing.synchronize.Event, queue: multiprocessing.queues.Queue) -> None:  # type: ignore[name-defined]
    binding = DIRECT.Binding(binding_bytes)
    start.wait()
    try:
        claim = JOURNAL.consume_for_effect_once(Path(local_state_dir), binding)
        JOURNAL.record_outcome_once(claim, outcome="unknown", evidence_sha256="d" * 64)
    except JOURNAL.DirectDurableJournalError as exc:
        queue.put(("rejected", str(exc)))
    else:
        queue.put(("claimed", "unknown"))


def _crash_after_started_worker(local_state_dir: str, binding_bytes: bytes) -> None:
    JOURNAL.consume_for_effect_once(Path(local_state_dir), DIRECT.Binding(binding_bytes))
    os._exit(23)


def _crash_after_manifest_worker(local_state_dir: str, binding_bytes: bytes) -> None:
    original = JOURNAL._write_new_file

    def write_then_crash(directory_fd: int, basename: str, raw: bytes, *, mode: int = 0o600) -> None:
        original(directory_fd, basename, raw, mode=mode)
        if basename == JOURNAL.MANIFEST_BASENAME:
            os._exit(29)

    JOURNAL._write_new_file = write_then_crash
    JOURNAL.consume_for_effect_once(Path(local_state_dir), DIRECT.Binding(binding_bytes))
    os._exit(30)


def _forked_claim_writer(
    claim: JOURNAL.DurableEffectClaim,
    journal_path: str,
    queue: object,
) -> None:
    before = tuple(sorted(item.name for item in Path(journal_path).iterdir()))
    try:
        JOURNAL.record_outcome_once(
            claim,
            outcome="unknown",
            evidence_sha256="0" * 63 + "1",
        )
    except JOURNAL.DirectDurableJournalError as exc:
        after = tuple(sorted(item.name for item in Path(journal_path).iterdir()))
        queue.put(
            (
                "rejected",
                str(exc),
                before == after,
                claim._directory_fd,
                claim._lock_fd,
            )
        )
    else:
        queue.put(("written", "", False, claim._directory_fd, claim._lock_fd))


class DirectDurableSubmissionJournalTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-direct-durable-")
        self.local_state_dir = Path(self.temporary.name).resolve()
        self.binding = self.build_binding()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build_binding(self) -> DIRECT.Binding:
        fixture = DirectRootFixture()
        fixture.authorization = ROOT_OWNER.build_direct_execution_authorization(
            authorization_id="direct-authorization-durable-001",
            profile=fixture.profile,
            stable_evidence=fixture.evidence,
            project=PROJECT,
            input_basename="input.gjf",
            input_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
            input_size_bytes=len(PAYLOAD),
            tier="simple",
            cores=8,
            memory_gb=12,
            walltime_seconds=3600,
            scientific_task_id=TASK,
            attempt_id=ATTEMPT,
            idempotency_key="direct-durable-001",
            approved_at="2026-07-28T23:59:00.000000Z",
            not_before="2026-07-29T00:00:00.000000Z",
            expires_at="2026-07-29T01:00:00.000000Z",
            maximum_receipt_age_seconds=60,
        )
        capability = fixture.capability()
        owner = ROOT_BOUNDARY.DirectRootMutationBoundaryOwner._for_testing(
            _test_token=ROOT_BOUNDARY._TEST_TOKEN
        )
        root_transaction = owner.issue_synthetic_transaction_once(
            root_capability=capability,
            helper=owner._synthetic_helper_for_testing(
                _test_token=ROOT_BOUNDARY._TEST_TOKEN
            ),
        )
        return DIRECT.build_binding(
            capability,
            root_transaction,
            DIRECT.ImmutableInput("input.gjf", PAYLOAD),
        )

    def journal_path(self, binding: DIRECT.Binding | None = None) -> Path:
        return self.local_state_dir / JOURNAL.journal_id_for_binding(binding or self.binding)

    def test_started_is_fsynced_before_non_authorizing_claim_and_second_claim_fails(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        journal_path = self.journal_path()
        self.assertEqual(claim.journal_id, journal_path.name)
        self.assertEqual(claim.outcome, "started")
        self.assertFalse(claim.authorizes_effect)
        self.assertTrue((journal_path / JOURNAL.MANIFEST_BASENAME).is_file())
        started = json.loads((journal_path / JOURNAL.STARTED_BASENAME).read_text(encoding="utf-8"))
        self.assertEqual((started["state"], started["outcome"]), ("submission_uncertain", "started"))
        with self.assertRaisesRegex(JOURNAL.DirectDurableJournalError, "already exists"):
            JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        JOURNAL.record_outcome_once(claim, outcome="unknown", evidence_sha256="a" * 64)

    def test_completed_and_explicit_unknown_are_append_only_terminal_outcomes(self) -> None:
        for outcome, evidence in (("completed", "b" * 64), ("unknown", "c" * 64)):
            with self.subTest(outcome=outcome):
                with tempfile.TemporaryDirectory(prefix="auto-g16-direct-outcome-") as temporary:
                    local_state_dir = Path(temporary).resolve()
                    claim = JOURNAL.consume_for_effect_once(local_state_dir, self.binding)
                    JOURNAL.record_outcome_once(claim, outcome=outcome, evidence_sha256=evidence)
                    snapshot = JOURNAL.reconcile_read_only(local_state_dir, claim.journal_id, self.binding).document()
                    self.assertEqual(snapshot["last_recorded_outcome"], outcome)
                    self.assertEqual(snapshot["effective_outcome"], outcome)
                    self.assertEqual(len(snapshot["events"]), 2)
                    self.assertFalse(snapshot["reconciliation"]["automatic_retry"])
                    self.assertFalse(snapshot["reconciliation"]["mutation_performed"])
                    with self.assertRaisesRegex(JOURNAL.DirectDurableJournalError, "already terminal"):
                        JOURNAL.record_outcome_once(claim, outcome=outcome, evidence_sha256=evidence)

    def test_process_crash_after_started_reconciles_unknown_and_never_reclaims(self) -> None:
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_crash_after_started_worker,
            args=(str(self.local_state_dir), self.binding._bytes),
        )
        process.start()
        process.join(20)
        self.assertEqual(process.exitcode, 23)
        journal_id = JOURNAL.journal_id_for_binding(self.binding)
        snapshot = JOURNAL.reconcile_read_only(self.local_state_dir, journal_id, self.binding).document()
        self.assertEqual(snapshot["last_recorded_outcome"], "started")
        self.assertEqual(snapshot["effective_outcome"], "unknown")
        self.assertEqual(len(snapshot["events"]), 1)
        before = self.directory_snapshot()
        with self.assertRaisesRegex(JOURNAL.DirectDurableJournalError, "only read-only reconciliation"):
            JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        self.assertEqual(self.directory_snapshot(), before)

    def test_crash_after_manifest_before_started_is_permanently_consumed_and_corrupt(self) -> None:
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_crash_after_manifest_worker,
            args=(str(self.local_state_dir), self.binding._bytes),
        )
        process.start()
        process.join(20)
        self.assertEqual(process.exitcode, 29)
        journal_id = JOURNAL.journal_id_for_binding(self.binding)
        path = self.local_state_dir / journal_id
        self.assertTrue((path / JOURNAL.MANIFEST_BASENAME).is_file())
        self.assertFalse((path / JOURNAL.STARTED_BASENAME).exists())
        before = self.directory_snapshot()
        with self.assertRaisesRegex(JOURNAL.DirectDurableJournalError, "only read-only reconciliation"):
            JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        with self.assertRaisesRegex(JOURNAL.DirectDurableJournalError, "absent or incomplete"):
            JOURNAL.reconcile_read_only(self.local_state_dir, journal_id, self.binding)
        self.assertEqual(self.directory_snapshot(), before)

    def test_hostile_multi_process_race_has_one_durable_winner(self) -> None:
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        queue = context.Queue()
        processes = [
            context.Process(
                target=_race_worker,
                args=(str(self.local_state_dir), self.binding._bytes, start, queue),
            )
            for _ in range(12)
        ]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(30)
            self.assertEqual(process.exitcode, 0)
        results = [queue.get(timeout=5) for _ in processes]
        self.assertEqual(sum(result[0] == "claimed" for result in results), 1)
        self.assertEqual(sum(result[0] == "rejected" for result in results), 11)
        journal_id = JOURNAL.journal_id_for_binding(self.binding)
        snapshot = JOURNAL.reconcile_read_only(self.local_state_dir, journal_id, self.binding).document()
        self.assertEqual(snapshot["effective_outcome"], "unknown")
        self.assertEqual([event["sequence"] for event in snapshot["events"]], [0, 1])

    def test_concurrent_terminal_conflict_has_one_append_and_claim_becomes_terminal(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        barrier = threading.Barrier(2)

        def finish(outcome: str) -> str:
            barrier.wait()
            try:
                JOURNAL.record_outcome_once(claim, outcome=outcome, evidence_sha256=("e" if outcome == "completed" else "f") * 64)
            except JOURNAL.DirectDurableJournalError:
                return "rejected"
            return outcome

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(finish, ("completed", "unknown")))
        self.assertEqual(sum(value in {"completed", "unknown"} for value in results), 1)
        self.assertEqual(results.count("rejected"), 1)
        snapshot = JOURNAL.reconcile_read_only(self.local_state_dir, claim.journal_id, self.binding).document()
        self.assertIn(snapshot["effective_outcome"], {"completed", "unknown"})
        self.assertEqual(len(snapshot["events"]), 2)

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "real fork start method is required")
    def test_forked_claim_child_fails_before_terminal_and_parent_writes_one_slot(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        child = context.Process(
            target=_forked_claim_writer,
            args=(claim, str(self.journal_path()), queue),
        )
        child.start()
        child.join(20)
        self.assertEqual(child.exitcode, 0)
        status, message, unchanged, child_directory_fd, child_lock_fd = queue.get(timeout=5)
        self.assertEqual(status, "rejected")
        self.assertRegex(message, "forked|wrong-process|registry")
        self.assertTrue(unchanged)
        self.assertEqual((child_directory_fd, child_lock_fd), (-1, -1))
        self.assertFalse((self.journal_path() / JOURNAL.TERMINAL_BASENAME).exists())

        JOURNAL.record_outcome_once(
            claim,
            outcome="completed",
            evidence_sha256="2" * 64,
        )
        terminal_files = list(self.journal_path().glob("000001-*"))
        self.assertEqual([item.name for item in terminal_files], [JOURNAL.TERMINAL_BASENAME])
        snapshot = JOURNAL.reconcile_read_only(
            self.local_state_dir,
            claim.journal_id,
            self.binding,
        ).document()
        self.assertEqual(snapshot["effective_outcome"], "completed")
        self.assertEqual(len(snapshot["events"]), 2)

    def test_forged_and_real_concurrent_writers_have_one_terminal_slot(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)

        def forged_claim() -> JOURNAL.DurableEffectClaim:
            forged = object.__new__(JOURNAL.DurableEffectClaim)
            forged._binding_sha256 = claim._binding_sha256
            forged._closed = False
            forged._creator_pid = claim._creator_pid
            forged._directory_fd = os.dup(claim._directory_fd)
            forged._journal_id = claim._journal_id
            forged._lock = threading.Lock()
            forged._lock_fd = os.dup(claim._lock_fd)
            forged._process_epoch = claim._process_epoch
            forged._registry_nonce = claim._registry_nonce
            forged._started_event_sha256 = claim._started_event_sha256
            forged._token = claim._token
            return forged

        forged_one = forged_claim()
        forged_two = forged_claim()
        barrier = threading.Barrier(3)

        def write(candidate: JOURNAL.DurableEffectClaim, outcome: str, evidence: str) -> str:
            barrier.wait()
            try:
                JOURNAL.record_outcome_once(
                    candidate,
                    outcome=outcome,
                    evidence_sha256=evidence,
                )
            except JOURNAL.DirectDurableJournalError as exc:
                return "registry" if "registry" in str(exc) else "rejected"
            finally:
                if candidate is not claim:
                    for name in ("_lock_fd", "_directory_fd"):
                        descriptor = getattr(candidate, name, -1)
                        if type(descriptor) is int and descriptor >= 0:
                            os.close(descriptor)
                            object.__setattr__(candidate, name, -1)
                    object.__setattr__(candidate, "_closed", True)
            return "written"

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = (
                pool.submit(write, claim, "completed", "3" * 64),
                pool.submit(write, forged_one, "unknown", "4" * 64),
                pool.submit(write, forged_two, "unknown", "5" * 64),
            )
            results = [future.result() for future in futures]
        self.assertEqual(results.count("written"), 1)
        self.assertEqual(results.count("registry"), 2)
        terminal_files = list(self.journal_path().glob("000001-*"))
        self.assertEqual([item.name for item in terminal_files], [JOURNAL.TERMINAL_BASENAME])
        snapshot = JOURNAL.reconcile_read_only(
            self.local_state_dir,
            claim.journal_id,
            self.binding,
        ).document()
        self.assertEqual(snapshot["effective_outcome"], "completed")
        self.assertEqual(len(snapshot["events"]), 2)

    def test_shared_terminal_slot_rejects_competing_outcome_without_overwrite(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        competing = JOURNAL._event(
            journal_id=claim._journal_id,
            binding_sha256=claim._binding_sha256,
            sequence=1,
            event_type="effect_outcome_unknown",
            outcome="unknown",
            previous_event_sha256=claim._started_event_sha256,
            evidence_sha256="6" * 64,
        )
        JOURNAL._write_new_file(
            claim._directory_fd,
            JOURNAL.TERMINAL_BASENAME,
            JOURNAL.canonical_bytes(competing),
        )
        terminal_path = self.journal_path() / JOURNAL.TERMINAL_BASENAME
        before = terminal_path.read_bytes()
        with self.assertRaisesRegex(
            JOURNAL.DirectDurableJournalError,
            "terminal append failed closed",
        ):
            JOURNAL.record_outcome_once(
                claim,
                outcome="completed",
                evidence_sha256="7" * 64,
            )
        self.assertEqual(terminal_path.read_bytes(), before)
        self.assertEqual(len(list(self.journal_path().glob("000001-*"))), 1)
        snapshot = JOURNAL.reconcile_read_only(
            self.local_state_dir,
            claim.journal_id,
            self.binding,
        ).document()
        self.assertEqual(snapshot["effective_outcome"], "unknown")
        self.assertEqual(len(snapshot["events"]), 2)

    def test_scope_profile_hash_attempt_and_resource_drift_fail_closed_without_write(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        JOURNAL.record_outcome_once(claim, outcome="unknown", evidence_sha256="1" * 64)
        journal_id = claim.journal_id
        baseline = self.binding.document()
        changes = (
            ("profile", "profile_payload_sha256", "2" * 64),
            ("authorization", "authorization_scope_sha256", "3" * 64),
            ("scope", "attempt_id", "qsub-attempt-" + "4" * 64),
            ("resources", "cores", "9"),
            ("input", "sha256", "5" * 64),
        )
        before = self.directory_snapshot()
        for container, field, value in changes:
            with self.subTest(container=container, field=field):
                changed = copy.deepcopy(baseline)
                changed[container][field] = value
                changed = DIRECT.finalized(changed, "binding_payload_sha256")
                drifted = DIRECT.Binding(DIRECT.canonical_bytes(changed))
                with self.assertRaises(JOURNAL.DirectDurableJournalError):
                    JOURNAL.reconcile_read_only(self.local_state_dir, journal_id, drifted)
                self.assertEqual(self.directory_snapshot(), before)

    def test_corruption_unknown_entry_conflicting_terminal_and_mode_drift_fail_closed(self) -> None:
        cases: list[tuple[str, callable]] = []

        def corrupt_started(path: Path) -> None:
            (path / JOURNAL.STARTED_BASENAME).write_bytes(b"{\"broken\":true}\n")

        def add_unknown_entry(path: Path) -> None:
            (path / "unexpected.bin").write_bytes(b"x")

        def obsolete_second_terminal(path: Path) -> None:
            (path / "000001-completed.json").write_bytes(
                (path / JOURNAL.TERMINAL_BASENAME).read_bytes()
            )

        def mode_drift(path: Path) -> None:
            os.chmod(path / JOURNAL.MANIFEST_BASENAME, 0o666)

        cases.extend((
            ("corrupt", corrupt_started),
            ("unknown-entry", add_unknown_entry),
            ("obsolete-second-terminal", obsolete_second_terminal),
            ("mode", mode_drift),
        ))
        for label, mutate in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory(prefix="auto-g16-direct-corrupt-") as temporary:
                    local_state_dir = Path(temporary).resolve()
                    claim = JOURNAL.consume_for_effect_once(local_state_dir, self.binding)
                    JOURNAL.record_outcome_once(claim, outcome="completed", evidence_sha256="6" * 64)
                    path = local_state_dir / claim.journal_id
                    mutate(path)
                    before = self.directory_snapshot(path)
                    with self.assertRaises(JOURNAL.DirectDurableJournalError):
                        JOURNAL.reconcile_read_only(local_state_dir, claim.journal_id, self.binding)
                    self.assertEqual(self.directory_snapshot(path), before)

    def test_symlink_and_insecure_local_state_are_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-direct-parent-") as temporary:
            parent = Path(temporary).resolve()
            real = parent / "real"
            real.mkdir(mode=0o700)
            linked = parent / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with self.assertRaises((JOURNAL.DirectDurableJournalError, OSError)):
                JOURNAL.consume_for_effect_once(linked, self.binding)
            self.assertEqual(list(real.iterdir()), [])
            os.chmod(real, 0o777)
            with self.assertRaisesRegex(JOURNAL.DirectDurableJournalError, "ownership or mode"):
                JOURNAL.consume_for_effect_once(real, self.binding)
            self.assertEqual(list(real.iterdir()), [])

    def test_claim_is_exact_noncopyable_nonserializable_and_foreign_claim_rejected(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(TypeError):
                    operation(claim)
        with self.assertRaises(TypeError):
            JOURNAL.DurableEffectClaim()
        bare_forgery = object.__new__(JOURNAL.DurableEffectClaim)
        with self.assertRaisesRegex(
            JOURNAL.DirectDurableJournalError,
            "forked, foreign, or wrong-process",
        ):
            JOURNAL.record_outcome_once(
                bare_forgery,
                outcome="unknown",
                evidence_sha256="7" * 64,
            )
        with self.assertRaises(JOURNAL.DirectDurableJournalError):
            JOURNAL.record_outcome_once(object(), outcome="unknown", evidence_sha256="7" * 64)  # type: ignore[arg-type]
        JOURNAL.record_outcome_once(claim, outcome="unknown", evidence_sha256="7" * 64)

    def test_registered_claim_canonical_field_mutations_fail_before_terminal_write(self) -> None:
        mutations = (
            ("_binding_sha256", lambda claim: "f" * 64),
            ("_journal_id", lambda claim: JOURNAL.JOURNAL_PREFIX + "f" * 64),
            ("_started_event_sha256", lambda claim: "f" * 64),
            ("_closed", lambda claim: True),
            ("_creator_pid", lambda claim: claim._creator_pid + 100_000),
            ("_process_epoch", lambda claim: object()),
            ("_registry_nonce", lambda claim: object()),
            ("_token", lambda claim: object()),
            ("_lock", lambda claim: threading.Lock()),
        )
        for field, replacement in mutations:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory(prefix="auto-g16-direct-claim-field-") as temporary:
                    local_state_dir = Path(temporary).resolve()
                    claim = JOURNAL.consume_for_effect_once(local_state_dir, self.binding)
                    journal_id = claim.journal_id
                    object.__setattr__(claim, field, replacement(claim))
                    with self.assertRaisesRegex(
                        JOURNAL.DirectDurableJournalError,
                        "claim|registry|forked|wrong-process|terminal",
                    ):
                        JOURNAL.record_outcome_once(
                            claim,
                            outcome="completed",
                            evidence_sha256="e" * 64,
                        )
                    journal_path = local_state_dir / journal_id
                    self.assertFalse((journal_path / JOURNAL.TERMINAL_BASENAME).exists())
                    self.assertTrue(claim._closed)
                    self.assertEqual((claim._directory_fd, claim._lock_fd), (-1, -1))
                    with self.assertRaises(JOURNAL.DirectDurableJournalError):
                        JOURNAL.record_outcome_once(
                            claim,
                            outcome="unknown",
                            evidence_sha256="b" * 64,
                        )
                    snapshot = JOURNAL.reconcile_read_only(
                        local_state_dir,
                        journal_id,
                        self.binding,
                    ).document()
                    self.assertEqual(snapshot["effective_outcome"], "unknown")
                    self.assertEqual(len(snapshot["events"]), 1)

    def test_owner_registry_is_closure_private_and_synchronized_forgery_fails(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        journal_id = claim.journal_id
        namespace = vars(JOURNAL)
        self.assertNotIn("_CLAIM_REGISTRY", namespace)
        self.assertNotIn("_CLAIM_REGISTRY_LOCK", namespace)
        for name, value in namespace.items():
            if "registry" in name.lower():
                self.assertNotIsInstance(value, Mapping, name)
        self.assertFalse(any(type(value) is JOURNAL._ClaimRecord for value in namespace.values()))

        access = JOURNAL._claim_owner_access(claim)
        self.assertIs(type(access), JOURNAL._ClaimAccess)
        self.assertTrue(issubclass(JOURNAL._ClaimRecord, tuple))
        self.assertTrue(issubclass(JOURNAL._DescriptorIdentity, tuple))
        self.assertTrue(issubclass(JOURNAL._ClaimAccess, tuple))
        self.assertTrue(JOURNAL.POLICY["closure_private_claim_registry"])
        self.assertTrue(JOURNAL.POLICY["immutable_claim_registry_records"])
        self.assertFalse(JOURNAL.POLICY["arbitrary_same_process_reflection_isolated"])
        forged_record = JOURNAL._ClaimRecord(
            registry_nonce=access.registry_nonce,
            creator_pid=claim._creator_pid,
            process_epoch=claim._process_epoch,
            claim_reference=weakref.ref(claim),
            binding_sha256=claim._binding_sha256,
            journal_id=claim._journal_id,
            started_event_sha256="f" * 64,
            directory_identity=access.directory_identity,
            lock_identity=access.lock_identity,
            thread_lock=access.thread_lock,
        )
        for immutable, field in (
            (forged_record, "started_event_sha256"),
            (access, "started_event_sha256"),
            (access.directory_identity, "inode"),
        ):
            with self.subTest(immutable=type(immutable).__name__):
                with self.assertRaises((AttributeError, TypeError)):
                    object.__setattr__(immutable, field, "f" * 64)

        object.__setattr__(claim, "_started_event_sha256", "f" * 64)
        JOURNAL._CLAIM_REGISTRY = {id(claim): forged_record}
        try:
            with self.assertRaises(JOURNAL.DirectDurableJournalError):
                JOURNAL.record_outcome_once(
                    claim,
                    outcome="completed",
                    evidence_sha256="e" * 64,
                )
        finally:
            del JOURNAL._CLAIM_REGISTRY
        self.assertFalse((self.journal_path() / JOURNAL.TERMINAL_BASENAME).exists())
        self.assertTrue(claim._closed)
        self.assertEqual((claim._directory_fd, claim._lock_fd), (-1, -1))
        with self.assertRaises(JOURNAL.DirectDurableJournalError):
            JOURNAL.record_outcome_once(
                claim,
                outcome="unknown",
                evidence_sha256="d" * 64,
            )
        snapshot = JOURNAL.reconcile_read_only(
            self.local_state_dir,
            journal_id,
            self.binding,
        ).document()
        self.assertEqual(snapshot["effective_outcome"], "unknown")
        self.assertEqual(len(snapshot["events"]), 1)

    def test_registered_claim_descriptor_field_replacement_fails_before_terminal_write(self) -> None:
        for field in ("_directory_fd", "_lock_fd"):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory(prefix="auto-g16-direct-claim-fd-field-") as temporary:
                    local_state_dir = Path(temporary).resolve()
                    claim = JOURNAL.consume_for_effect_once(local_state_dir, self.binding)
                    journal_id = claim.journal_id
                    replacement = os.dup(getattr(claim, field))
                    object.__setattr__(claim, field, replacement)
                    try:
                        with self.assertRaisesRegex(
                            JOURNAL.DirectDurableJournalError,
                            "descriptor fields",
                        ):
                            JOURNAL.record_outcome_once(
                                claim,
                                outcome="completed",
                                evidence_sha256="d" * 64,
                            )
                    finally:
                        os.close(replacement)
                    journal_path = local_state_dir / journal_id
                    self.assertFalse((journal_path / JOURNAL.TERMINAL_BASENAME).exists())
                    self.assertTrue(claim._closed)
                    self.assertEqual((claim._directory_fd, claim._lock_fd), (-1, -1))
                    with self.assertRaises(JOURNAL.DirectDurableJournalError):
                        JOURNAL.record_outcome_once(
                            claim,
                            outcome="unknown",
                            evidence_sha256="b" * 64,
                        )
                    snapshot = JOURNAL.reconcile_read_only(
                        local_state_dir,
                        journal_id,
                        self.binding,
                    ).document()
                    self.assertEqual(snapshot["effective_outcome"], "unknown")
                    self.assertEqual(len(snapshot["events"]), 1)

    def test_registered_claim_closed_or_reused_descriptor_fails_before_terminal_write(self) -> None:
        cases = (
            ("_directory_fd", "closed"),
            ("_lock_fd", "closed"),
            ("_directory_fd", "reused"),
            ("_lock_fd", "reused"),
        )
        for field, state in cases:
            with self.subTest(field=field, state=state):
                with tempfile.TemporaryDirectory(prefix="auto-g16-direct-claim-fd-live-") as temporary:
                    local_state_dir = Path(temporary).resolve()
                    claim = JOURNAL.consume_for_effect_once(local_state_dir, self.binding)
                    journal_id = claim.journal_id
                    descriptor = getattr(claim, field)
                    os.close(descriptor)
                    descriptor_is_live = False
                    decoy_path = local_state_dir / "decoy"
                    if state == "reused":
                        if field == "_directory_fd":
                            decoy_path.mkdir(mode=0o700)
                            replacement = os.open(
                                decoy_path,
                                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
                            )
                        else:
                            replacement = os.open(
                                decoy_path,
                                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                                0o600,
                            )
                        if replacement != descriptor:
                            os.dup2(replacement, descriptor)
                            os.close(replacement)
                        descriptor_is_live = True
                    try:
                        with self.assertRaisesRegex(
                            JOURNAL.DirectDurableJournalError,
                            "descriptor.*(?:closed|invalid|identity)",
                        ):
                            JOURNAL.record_outcome_once(
                                claim,
                                outcome="unknown",
                                evidence_sha256="c" * 64,
                            )
                    finally:
                        if descriptor_is_live:
                            os.close(descriptor)
                    journal_path = local_state_dir / journal_id
                    self.assertFalse((journal_path / JOURNAL.TERMINAL_BASENAME).exists())
                    if decoy_path.is_dir():
                        self.assertFalse((decoy_path / JOURNAL.TERMINAL_BASENAME).exists())
                    self.assertTrue(claim._closed)
                    self.assertEqual((claim._directory_fd, claim._lock_fd), (-1, -1))
                    with self.assertRaises(JOURNAL.DirectDurableJournalError):
                        JOURNAL.record_outcome_once(
                            claim,
                            outcome="completed",
                            evidence_sha256="b" * 64,
                        )
                    snapshot = JOURNAL.reconcile_read_only(
                        local_state_dir,
                        journal_id,
                        self.binding,
                    ).document()
                    self.assertEqual(snapshot["effective_outcome"], "unknown")
                    self.assertEqual(len(snapshot["events"]), 1)

    def test_reconciliation_is_byte_for_byte_read_only(self) -> None:
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        JOURNAL.record_outcome_once(claim, outcome="completed", evidence_sha256="8" * 64)
        before = self.directory_snapshot()
        snapshots = [
            JOURNAL.reconcile_read_only(self.local_state_dir, claim.journal_id, self.binding).document()
            for _ in range(10)
        ]
        self.assertTrue(all(snapshot["journal_payload_sha256"] == snapshots[0]["journal_payload_sha256"] for snapshot in snapshots))
        self.assertEqual(self.directory_snapshot(), before)

    def test_module_reload_and_foreign_canonical_reexecution_fail_closed(self) -> None:
        with self.assertRaisesRegex(ImportError, "already executed"):
            importlib.reload(JOURNAL)
        source = SCRIPTS / "direct_durable_submission_journal.py"
        spec = importlib.util.spec_from_file_location(JOURNAL.MODULE_NAME, source)
        assert spec and spec.loader
        foreign = importlib.util.module_from_spec(spec)
        original = sys.modules[JOURNAL.MODULE_NAME]
        sys.modules[JOURNAL.MODULE_NAME] = foreign
        try:
            with self.assertRaisesRegex(Exception, "already registered"):
                spec.loader.exec_module(foreign)
        finally:
            sys.modules[JOURNAL.MODULE_NAME] = original
        claim = JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        JOURNAL.record_outcome_once(claim, outcome="unknown", evidence_sha256="9" * 64)

    def test_owner_and_direct_binding_class_drift_fail_before_local_write(self) -> None:
        original_claim = JOURNAL.DurableEffectClaim
        try:
            JOURNAL.DurableEffectClaim = object  # type: ignore[assignment]
            with self.assertRaisesRegex(JOURNAL.DirectDurableJournalError, "issued type identity"):
                JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        finally:
            JOURNAL.DurableEffectClaim = original_claim
        self.assertEqual(list(self.local_state_dir.iterdir()), [])

        original_binding = DIRECT.Binding
        try:
            DIRECT.Binding = object  # type: ignore[assignment]
            with self.assertRaisesRegex(JOURNAL.DirectDurableJournalError, "module or source identity"):
                JOURNAL.consume_for_effect_once(self.local_state_dir, self.binding)
        finally:
            DIRECT.Binding = original_binding
        self.assertEqual(list(self.local_state_dir.iterdir()), [])

    def test_no_effect_owner_or_legacy_surface_and_package_is_additive(self) -> None:
        tree = ast.parse((SCRIPTS / "direct_durable_submission_journal.py").read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "argparse", "subprocess", "socket", "paramiko", "legacy_rtwin_pbs",
            "direct_root_owner_contract", "resource_effect_time_replay_owner",
            "live_approval_effect_time_replay", "protected_job_runtime_coordinator",
        ):
            self.assertNotIn(forbidden, imports)
        source_text = (SCRIPTS / "direct_durable_submission_journal.py").read_text(encoding="utf-8")
        self.assertNotIn("/home/user100/SDL", source_text)
        self.assertNotIn("server_root", source_text)
        package = SKILL_PACKAGE.package_files_with_supplements(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(package[Path("scripts/direct_durable_submission_journal.py")], SCRIPTS / "direct_durable_submission_journal.py")
        self.assertEqual(package[Path("references/direct-durable-submission-journal.md")], ROOT / "docs/v2.7-direct-durable-submission-journal.md")
        self.assertEqual(
            package[Path("contracts/direct-execution/direct-durable-submission-journal.schema.json")],
            ROOT / "contracts/direct-execution/direct-durable-submission-journal.schema.json",
        )
        self.assertFalse((ROOT / "skills/auto-g16-rtwin-pbs/scripts/direct_durable_submission_journal.py").exists())

    def directory_snapshot(self, root: Path | None = None) -> dict[str, tuple[int, int, int, str]]:
        root = root or self.local_state_dir
        result: dict[str, tuple[int, int, int, str]] = {}
        for path in sorted(root.rglob("*")):
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            payload_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
            result[relative] = (info.st_mode, info.st_size, info.st_mtime_ns, payload_hash)
        return result


if __name__ == "__main__":
    unittest.main()
