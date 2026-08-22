"""Contract tests for immutable minimal Observe records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import unittest

import auto_g16.observe as observe


class AttemptObservationTests(unittest.TestCase):
    def sample(self, **changes: object) -> observe.AttemptObservation:
        values: dict[str, object] = {
            "attempt_id": "attempt-1",
            "source_kind": "scheduler",
            "source_identity": "source-qstat-1",
            "observed_at_utc": "2026-08-22T00:00:00.000000Z",
            "freshness": "fresh",
            "state": "running",
            "progress_position": None,
        }
        values.update(changes)
        return observe.AttemptObservation(**values)  # type: ignore[arg-type]

    def test_public_inventory_and_exact_fields_are_frozen(self) -> None:
        self.assertEqual(
            observe.__all__,
            [
                "OBSERVATION_TYPE",
                "AttemptObservation",
                "AttemptObservationProjection",
                "ObserveBoundaryError",
                "record_attempt_observation",
                "project_attempt_observations",
            ],
        )
        self.assertEqual(
            tuple(item.name for item in fields(observe.AttemptObservation)),
            (
                "observation_id",
                "attempt_id",
                "source_kind",
                "source_identity",
                "observed_at_utc",
                "freshness",
                "state",
                "progress_position",
            ),
        )
        self.assertEqual(
            tuple(item.name for item in fields(observe.AttemptObservationProjection)),
            (
                "attempt_id",
                "scheduler",
                "process",
                "gaussian",
                "observation_count",
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            self.sample().state = "terminal"  # type: ignore[misc]

    def test_normative_uuid_vector_and_exact_replay(self) -> None:
        first = self.sample()
        self.assertEqual(
            first.observation_id,
            "cdce89f6-8d2e-51b1-b5b0-7f6c48358e95",
        )
        self.assertEqual(first, self.sample())
        self.assertNotEqual(first.observation_id, self.sample(freshness="stale").observation_id)

    def test_every_closed_state_is_accepted(self) -> None:
        matrix = {
            "scheduler": (
                "queued",
                "running",
                "held",
                "exiting",
                "terminal",
                "absent",
                "unknown",
            ),
            "process": ("active", "absent", "unknown"),
            "gaussian": (
                "not-started",
                "startup",
                "scf",
                "optimization",
                "frequency",
                "termination",
                "unknown",
            ),
        }
        for source_kind, states in matrix.items():
            for state in states:
                with self.subTest(source_kind=source_kind, state=state):
                    progress = 0 if source_kind == "gaussian" else None
                    self.assertEqual(
                        self.sample(
                            source_kind=source_kind,
                            state=state,
                            progress_position=progress,
                        ).state,
                        state,
                    )

    def test_invalid_closed_fields_fail(self) -> None:
        cases = (
            {"attempt_id": ""},
            {"source_identity": ""},
            {"source_kind": "transport"},
            {"source_kind": []},
            {"freshness": "expired"},
            {"freshness": []},
            {"state": "failed"},
            {"state": []},
            {"observed_at_utc": "2026-08-22T00:00:00Z"},
            {"observed_at_utc": "2026-02-30T00:00:00.000000Z"},
            {"progress_position": 1},
            {
                "source_kind": "gaussian",
                "state": "scf",
                "progress_position": -1,
            },
            {
                "source_kind": "gaussian",
                "state": "scf",
                "progress_position": True,
            },
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(observe.ObserveBoundaryError):
                self.sample(**changes)

    def test_state_and_freshness_are_independent(self) -> None:
        for freshness in ("fresh", "stale", "unknown"):
            self.assertEqual(self.sample(freshness=freshness).state, "running")
            self.assertEqual(
                self.sample(freshness=freshness, state="unknown").freshness,
                freshness,
            )

    def test_unexpected_constructor_field_fails_closed(self) -> None:
        with self.assertRaises(TypeError):
            observe.AttemptObservation(  # type: ignore[call-arg]
                attempt_id="attempt-1",
                source_kind="scheduler",
                source_identity="source-1",
                observed_at_utc="2026-08-22T00:00:00.000000Z",
                freshness="fresh",
                state="running",
                progress_position=None,
                extra="not allowed",
            )


if __name__ == "__main__":
    unittest.main()
