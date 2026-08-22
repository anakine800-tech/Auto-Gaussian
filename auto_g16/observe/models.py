"""Immutable records for the frozen minimal Observe boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from typing import Final
from uuid import UUID, uuid5


OBSERVATION_TYPE: Final = "auto-g16-v3-attempt-observation"

_SCHEMA_VERSION: Final = 1
_NAMESPACE_ROOT: Final = UUID("653e9a6f-0d59-503c-ab13-ddd6e5055fe4")
_OBSERVATION_NAMESPACE: Final = uuid5(_NAMESPACE_ROOT, "attempt-observation")
_TIMESTAMP_PATTERN: Final = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z"
)
_FRESHNESS: Final = frozenset({"fresh", "stale", "unknown"})
_SOURCE_STATES: Final = {
    "scheduler": frozenset(
        {"queued", "running", "held", "exiting", "terminal", "absent", "unknown"}
    ),
    "process": frozenset({"active", "absent", "unknown"}),
    "gaussian": frozenset(
        {
            "not-started",
            "startup",
            "scf",
            "optimization",
            "frequency",
            "termination",
            "unknown",
        }
    ),
}


class ObserveBoundaryError(ValueError):
    """Observe input or persisted evidence violates the frozen boundary."""


def _require_nonempty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ObserveBoundaryError(f"{field_name} must be a non-empty string")
    return value


def _require_timestamp(value: object) -> str:
    timestamp = _require_nonempty_text(value, "observed_at_utc")
    if _TIMESTAMP_PATTERN.fullmatch(timestamp) is None:
        raise ObserveBoundaryError(
            "observed_at_utc must use exact YYYY-MM-DDTHH:MM:SS.ffffffZ syntax"
        )
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ObserveBoundaryError("observed_at_utc must denote a real UTC instant") from exc
    return timestamp


def _observation_identity(
    *,
    attempt_id: str,
    source_kind: str,
    source_identity: str,
    observed_at_utc: str,
    freshness: str,
    state: str,
    progress_position: int | None,
) -> str:
    payload = [
        _SCHEMA_VERSION,
        attempt_id,
        source_kind,
        source_identity,
        observed_at_utc,
        freshness,
        state,
        progress_position,
    ]
    name = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return str(uuid5(_OBSERVATION_NAMESPACE, name))


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptObservation:
    observation_id: str = field(init=False)
    attempt_id: str
    source_kind: str
    source_identity: str
    observed_at_utc: str
    freshness: str
    state: str
    progress_position: int | None

    def __post_init__(self) -> None:
        attempt_id = _require_nonempty_text(self.attempt_id, "attempt_id")
        source_identity = _require_nonempty_text(
            self.source_identity, "source_identity"
        )
        observed_at_utc = _require_timestamp(self.observed_at_utc)
        source_kind = _require_nonempty_text(self.source_kind, "source_kind")
        freshness = _require_nonempty_text(self.freshness, "freshness")
        state = _require_nonempty_text(self.state, "state")
        states = _SOURCE_STATES.get(source_kind)
        if states is None:
            raise ObserveBoundaryError("source_kind is not in the closed vocabulary")
        if freshness not in _FRESHNESS:
            raise ObserveBoundaryError("freshness is not in the closed vocabulary")
        if state not in states:
            raise ObserveBoundaryError("state is invalid for source_kind")
        if source_kind in {"scheduler", "process"}:
            if self.progress_position is not None:
                raise ObserveBoundaryError(
                    "scheduler and process progress_position must be None"
                )
        elif self.progress_position is not None and (
            isinstance(self.progress_position, bool)
            or not isinstance(self.progress_position, int)
            or self.progress_position < 0
        ):
            raise ObserveBoundaryError(
                "Gaussian progress_position must be None or a nonnegative integer"
            )
        object.__setattr__(
            self,
            "observation_id",
            _observation_identity(
                attempt_id=attempt_id,
                source_kind=source_kind,
                source_identity=source_identity,
                observed_at_utc=observed_at_utc,
                freshness=freshness,
                state=state,
                progress_position=self.progress_position,
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptObservationProjection:
    attempt_id: str
    scheduler: AttemptObservation | None
    process: AttemptObservation | None
    gaussian: AttemptObservation | None
    observation_count: int

    def __post_init__(self) -> None:
        _require_nonempty_text(self.attempt_id, "attempt_id")
        if (
            isinstance(self.observation_count, bool)
            or not isinstance(self.observation_count, int)
            or self.observation_count < 0
        ):
            raise ObserveBoundaryError("observation_count must be a nonnegative integer")
        for source_kind in _SOURCE_STATES:
            observation = getattr(self, source_kind)
            if observation is None:
                continue
            if (
                observation.attempt_id != self.attempt_id
                or observation.source_kind != source_kind
            ):
                raise ObserveBoundaryError(
                    "projection observations must match their Attempt and source axis"
                )
