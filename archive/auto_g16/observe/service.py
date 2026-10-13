"""Pure recording and projection services for minimal Observe evidence."""

from __future__ import annotations

from collections.abc import Mapping

from auto_g16.core import Observation, SQLiteRuntimeStore

from .models import (
    OBSERVATION_TYPE,
    AttemptObservation,
    AttemptObservationProjection,
    ObserveBoundaryError,
)


_PAYLOAD_FIELDS = frozenset(
    {
        "source_kind",
        "source_identity",
        "observed_at_utc",
        "freshness",
        "state",
        "progress_position",
    }
)


def _payload(observation: AttemptObservation) -> dict[str, object]:
    return {
        "source_kind": observation.source_kind,
        "source_identity": observation.source_identity,
        "observed_at_utc": observation.observed_at_utc,
        "freshness": observation.freshness,
        "state": observation.state,
        "progress_position": observation.progress_position,
    }


def _decode_observation(record: Observation) -> AttemptObservation:
    data: Mapping[str, object] = record.data
    if frozenset(data) != _PAYLOAD_FIELDS:
        raise ObserveBoundaryError("persisted Observe payload fields are not exact")
    try:
        observation = AttemptObservation(
            attempt_id=record.attempt_id,
            source_kind=data["source_kind"],  # type: ignore[arg-type]
            source_identity=data["source_identity"],  # type: ignore[arg-type]
            observed_at_utc=data["observed_at_utc"],  # type: ignore[arg-type]
            freshness=data["freshness"],  # type: ignore[arg-type]
            state=data["state"],  # type: ignore[arg-type]
            progress_position=data["progress_position"],  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ObserveBoundaryError) as exc:
        raise ObserveBoundaryError("persisted Observe payload is malformed") from exc
    if observation.observation_id != record.observation_id:
        raise ObserveBoundaryError("persisted Observe identity is inconsistent")
    return observation


def record_attempt_observation(
    store: SQLiteRuntimeStore,
    observation: AttemptObservation,
) -> None:
    """Append one exact, already source-classified observation to Core."""

    store.load_attempt(observation.attempt_id)
    verified = AttemptObservation(
        attempt_id=observation.attempt_id,
        source_kind=observation.source_kind,
        source_identity=observation.source_identity,
        observed_at_utc=observation.observed_at_utc,
        freshness=observation.freshness,
        state=observation.state,
        progress_position=observation.progress_position,
    )
    if verified.observation_id != observation.observation_id:
        raise ObserveBoundaryError("AttemptObservation identity is inconsistent")
    store.append_observation(
        Observation(
            observation_id=observation.observation_id,
            attempt_id=observation.attempt_id,
            observation_type=OBSERVATION_TYPE,
            data=_payload(observation),
        )
    )


def project_attempt_observations(
    store: SQLiteRuntimeStore,
    *,
    attempt_id: str,
) -> AttemptObservationProjection:
    """Validate complete persisted Observe history and project last append per axis."""

    attempt = store.load_attempt(attempt_id)
    projected: dict[str, AttemptObservation | None] = {
        "scheduler": None,
        "process": None,
        "gaussian": None,
    }
    observation_count = 0
    for record in store.observations_for_attempt(attempt.attempt_id):
        if record.observation_type != OBSERVATION_TYPE:
            continue
        observation = _decode_observation(record)
        if observation.attempt_id != attempt.attempt_id:
            raise ObserveBoundaryError("persisted Observe record crosses Attempts")
        projected[observation.source_kind] = observation
        observation_count += 1
    return AttemptObservationProjection(
        attempt_id=attempt.attempt_id,
        scheduler=projected["scheduler"],
        process=projected["process"],
        gaussian=projected["gaussian"],
        observation_count=observation_count,
    )
