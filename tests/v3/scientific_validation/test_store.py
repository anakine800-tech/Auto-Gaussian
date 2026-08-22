"""Append-only ScientificValidation persistence and acceptance evidence."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from auto_g16.scientific_validation.models import _identity

from auto_g16.scientific_validation import (
    MinimumValidationClassification as Classification,
    SQLiteScientificValidationStore,
    ScientificValidationConflictError,
    ScientificValidationError,
    ScientificValidationPersistenceIntegrityError,
    record_minimum_validation,
    record_scientific_acceptance,
    require_scientific_acceptance,
    validate_minimum,
)

from ._fixtures import stored_chain


class ScientificValidationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "scientific-validation.sqlite3"

    def outcome(self, **facts_options: object):  # type: ignore[no-untyped-def]
        core, binding, envelope, parse_outcome = stored_chain(
            facts_options=facts_options
        )
        self.addCleanup(core.close)
        return validate_minimum(core, binding, envelope, parse_outcome)

    @staticmethod
    def _reidentify(payload: dict[str, object]) -> None:
        authority = {
            key: value
            for key, value in payload.items()
            if key != "minimum_validation_outcome_id"
        }
        payload["minimum_validation_outcome_id"] = _identity(
            "minimum-validation-outcome", authority
        )

    def _rewrite_outcome_row(
        self,
        store: SQLiteScientificValidationStore,
        outcome_id: str,
        mutate: Callable[[dict[str, object]], None],
    ) -> str:
        row = store._connection.execute(  # type: ignore[attr-defined]
            "SELECT payload_json FROM minimum_validations "
            "WHERE minimum_validation_outcome_id = ?",
            (outcome_id,),
        ).fetchone()
        payload = json.loads(row[0])
        mutate(payload)
        self._reidentify(payload)
        forged_id = payload["minimum_validation_outcome_id"]
        store._connection.execute(  # type: ignore[attr-defined]
            "UPDATE minimum_validations SET minimum_validation_outcome_id = ?, "
            "payload_json = ? WHERE minimum_validation_outcome_id = ?",
            (
                forged_id,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                outcome_id,
            ),
        )
        return forged_id  # type: ignore[return-value]

    def test_exact_replay_is_idempotent_and_durable_order_survives_reopen(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        first = self.outcome()
        second = self.outcome(frequencies=(-1e-12, 100.0, 200.0))
        self.assertEqual(record_minimum_validation(store, first), first)
        self.assertEqual(record_minimum_validation(store, first), first)
        record_minimum_validation(store, second)
        self.assertEqual(
            store.minimum_validations_for_attempt("attempt-1"), (first, second)
        )
        store.close()

        reopened = SQLiteScientificValidationStore.open_existing(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.load_minimum_validation(first.minimum_validation_outcome_id), first)
        self.assertEqual(
            reopened.minimum_validations_for_attempt("attempt-1"), (first, second)
        )

    def test_same_identity_with_changed_content_conflicts(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        self.addCleanup(store.close)
        item = self.outcome()
        record_minimum_validation(store, item)
        object.__setattr__(item, "reason_code", "negative-frequency")
        with self.assertRaises(ScientificValidationConflictError):
            record_minimum_validation(store, item)

    def test_acceptance_requires_persisted_validated_outcome_and_exact_ids(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        self.addCleanup(store.close)
        validated = self.outcome()
        negative = self.outcome(frequencies=(-1.0, 100.0, 200.0))
        with self.assertRaises(ScientificValidationError):
            record_scientific_acceptance(
                store,
                minimum_validation_outcome_id=validated.minimum_validation_outcome_id,
                reviewer_id="reviewer-1",
                review_evidence={"decision": "accept"},
            )
        record_minimum_validation(store, validated)
        record_minimum_validation(store, negative)
        with self.assertRaises(ScientificValidationError):
            record_scientific_acceptance(
                store,
                minimum_validation_outcome_id=negative.minimum_validation_outcome_id,
                reviewer_id="reviewer-1",
                review_evidence={"decision": "accept"},
            )
        acceptance = record_scientific_acceptance(
            store,
            minimum_validation_outcome_id=validated.minimum_validation_outcome_id,
            reviewer_id="reviewer-1",
            review_evidence={"decision": "accept", "reviewed": True},
        )
        self.assertEqual(
            require_scientific_acceptance(
                store,
                minimum_validation_outcome_id=validated.minimum_validation_outcome_id,
                scientific_acceptance_id=acceptance.scientific_acceptance_id,
            ),
            (validated, acceptance),
        )
        with self.assertRaises(ScientificValidationError):
            require_scientific_acceptance(
                store,
                minimum_validation_outcome_id=negative.minimum_validation_outcome_id,
                scientific_acceptance_id=acceptance.scientific_acceptance_id,
            )

    def test_multiple_explicit_acceptances_have_no_latest_pointer(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        self.addCleanup(store.close)
        outcome = record_minimum_validation(store, self.outcome())
        first = record_scientific_acceptance(
            store,
            minimum_validation_outcome_id=outcome.minimum_validation_outcome_id,
            reviewer_id="reviewer-1",
            review_evidence={"decision": "accept", "ordinal": 1},
        )
        second = record_scientific_acceptance(
            store,
            minimum_validation_outcome_id=outcome.minimum_validation_outcome_id,
            reviewer_id="reviewer-2",
            review_evidence={"decision": "accept", "ordinal": 2},
        )
        self.assertNotEqual(first.scientific_acceptance_id, second.scientific_acceptance_id)
        self.assertEqual(store.acceptances_for_outcome(outcome.minimum_validation_outcome_id), (first, second))

    def test_tagged_identity_distinguishes_boolean_and_integer_and_sorts_mappings(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        self.addCleanup(store.close)
        outcome = record_minimum_validation(store, self.outcome())
        boolean = record_scientific_acceptance(
            store,
            minimum_validation_outcome_id=outcome.minimum_validation_outcome_id,
            reviewer_id="reviewer",
            review_evidence={"z": 2, "value": True},
        )
        integer = record_scientific_acceptance(
            store,
            minimum_validation_outcome_id=outcome.minimum_validation_outcome_id,
            reviewer_id="reviewer",
            review_evidence={"value": 1, "z": 2},
        )
        reordered = record_scientific_acceptance(
            store,
            minimum_validation_outcome_id=outcome.minimum_validation_outcome_id,
            reviewer_id="reviewer",
            review_evidence={"value": True, "z": 2},
        )
        self.assertNotEqual(boolean.scientific_acceptance_id, integer.scientific_acceptance_id)
        self.assertEqual(boolean, reordered)

    def test_create_is_exclusive_and_terminal_symlink_reopen_fails_closed(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        store.close()
        with self.assertRaises(ScientificValidationPersistenceIntegrityError):
            SQLiteScientificValidationStore.create_new(self.path)
        alias = Path(self.temporary.name) / "alias.sqlite3"
        alias.symlink_to(self.path)
        with self.assertRaises(ScientificValidationPersistenceIntegrityError):
            SQLiteScientificValidationStore.open_existing(alias)

    def test_open_store_detects_terminal_replacement_before_reads(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        outcome = self.outcome()
        record_minimum_validation(store, outcome)
        displaced = Path(self.temporary.name) / "displaced.sqlite3"
        self.path.rename(displaced)
        replacement = SQLiteScientificValidationStore.create_new(self.path)
        replacement.close()
        with self.assertRaises(ScientificValidationPersistenceIntegrityError):
            store.load_minimum_validation(outcome.minimum_validation_outcome_id)
        store.close()

    def test_unexpected_schema_object_and_malformed_row_fail_on_reopen(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        outcome = record_minimum_validation(store, self.outcome())
        store.close()
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE unexpected(value TEXT)")
        connection.commit()
        connection.close()
        with self.assertRaises(ScientificValidationPersistenceIntegrityError):
            SQLiteScientificValidationStore.open_existing(self.path)

        other = Path(self.temporary.name) / "malformed.sqlite3"
        store = SQLiteScientificValidationStore.create_new(other)
        record_minimum_validation(store, outcome)
        store.close()
        connection = sqlite3.connect(other)
        connection.execute(
            "UPDATE minimum_validations SET payload_json = '{\"broken\":true}'"
        )
        connection.commit()
        connection.close()
        with self.assertRaises(ScientificValidationPersistenceIntegrityError):
            SQLiteScientificValidationStore.open_existing(other)

    def test_recomputed_identity_cannot_authorize_contradictory_semantics(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        self.addCleanup(store.close)
        outcome = record_minimum_validation(store, self.outcome())

        def contradict_reason(payload: dict[str, object]) -> None:
            payload["reason_code"] = "negative-frequency"

        forged_id = self._rewrite_outcome_row(
            store,
            outcome.minimum_validation_outcome_id,
            contradict_reason,
        )
        with self.assertRaises(ScientificValidationPersistenceIntegrityError):
            store.load_minimum_validation(forged_id)
        with self.assertRaises(ScientificValidationPersistenceIntegrityError):
            record_scientific_acceptance(
                store,
                minimum_validation_outcome_id=forged_id,
                reviewer_id="reviewer-1",
                review_evidence={"decision": "accept"},
            )

    def test_recomputed_identity_cannot_splice_selected_frequency_projection(self) -> None:
        store = SQLiteScientificValidationStore.create_new(self.path)
        self.addCleanup(store.close)
        outcome = record_minimum_validation(store, self.outcome())

        def contradict_projection(payload: dict[str, object]) -> None:
            payload["selected_frequencies_cm1"] = [-1.0, 200.0, 300.0]
            payload["classification"] = Classification.NOT_MINIMUM.value
            payload["reason_code"] = "negative-frequency"

        forged_id = self._rewrite_outcome_row(
            store,
            outcome.minimum_validation_outcome_id,
            contradict_projection,
        )
        with self.assertRaises(ScientificValidationPersistenceIntegrityError):
            store.load_minimum_validation(forged_id)


if __name__ == "__main__":
    unittest.main()
