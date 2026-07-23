"""Offline-verifiable wiring for the sole v2.6 legacy adapter.

This module owns no transport command, validator, artifact schema, retry, or
cleanup behavior.  It replays the existing successor owner, reserves the
existing trusted single-use state, and then hands one sealed value to the
fixed legacy adapter exactly once.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from execution_authorization_state import (
    ConsumptionRequest,
    ConsumedAuthorization,
    TrustedAuthorizationStateOwner,
)
from execution_models import _load_repository_owner


_INTEGRATION_FACTORY_TOKEN = object()
_RESERVED_ATTEMPT_TOKEN = object()
_OWNER_LOCK = threading.RLock()
_OWNER_MODULE: Any | None = None


class LegacyAdapterIntegrationError(RuntimeError):
    """The owner replay, reservation, or fixed adapter handoff failed."""


class LegacyAdapterInvocationUncertain(LegacyAdapterIntegrationError):
    """The single adapter invocation raised after the reservation was kept."""

    def __init__(self, message: str, reservation: "ReservedLegacyAttempt") -> None:
        super().__init__(message)
        self.reservation = reservation


@dataclass(frozen=True, slots=True)
class SuccessorAuthorityArtifacts:
    """Exact in-memory artifacts consumed by their existing owners."""

    successor_request: Mapping[str, Any]
    successor_authorization: Mapping[str, Any]
    base_request: Mapping[str, Any]
    base_authorization: Mapping[str, Any]
    profile_v1: Mapping[str, Any]
    profile_v2: Mapping[str, Any]
    identity_binding: Mapping[str, Any]
    first_hop_request: Mapping[str, Any]
    first_hop_receipt: Mapping[str, Any]
    nested_hop_request: Mapping[str, Any]
    nested_hop_receipt: Mapping[str, Any]
    handshake_request: Mapping[str, Any]
    handshake_observation: Mapping[str, Any]
    handshake_receipt: Mapping[str, Any]

    def owner_snapshot(self) -> dict[str, dict[str, Any]]:
        snapshot: dict[str, dict[str, Any]] = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise LegacyAdapterIntegrationError(f"{name} must be a mapping")
            snapshot[name] = copy.deepcopy(dict(value))
        return snapshot


@dataclass(frozen=True, slots=True)
class LegacyAttemptBinding:
    """Existing attempt/idempotency values; no host, path, or command input."""

    attempt_id: str
    idempotency_key_sha256: str
    consumed_at: str


@dataclass(frozen=True, slots=True, init=False)
class ReservedLegacyAttempt:
    """Owner-sealed handoff presented to the fixed legacy adapter once."""

    authorization_id: str
    authorization_sha256: str
    attempt_id: str
    readiness_sha256: str
    handshake_receipt_sha256: str
    consumption_sha256: str
    attestation_nonces: tuple[str, ...]
    submission_state: str
    automatic_retry: bool
    reconcile_only_if_uncertain: bool
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "ReservedLegacyAttempt":
        raise TypeError("ReservedLegacyAttempt is issued only after trusted reservation")

    @classmethod
    def _from_consumption(
        cls,
        *,
        consumption: ConsumedAuthorization,
        request: ConsumptionRequest,
        handshake_receipt_sha256: str,
        token: object,
    ) -> "ReservedLegacyAttempt":
        if token is not _RESERVED_ATTEMPT_TOKEN:
            raise LegacyAdapterIntegrationError("reserved attempt factory is invalid")
        if (
            consumption.consumed is not True
            or consumption.submission_state != "submission_uncertain"
            or consumption.authorization_id != request.authorization_id
            or consumption.attempt_id != request.attempt_id
        ):
            raise LegacyAdapterIntegrationError("trusted consumption result differs from the exact attempt")
        value = object.__new__(cls)
        for name, item in {
            "authorization_id": request.authorization_id,
            "authorization_sha256": request.authorization_sha256,
            "attempt_id": request.attempt_id,
            "readiness_sha256": request.readiness_sha256,
            "handshake_receipt_sha256": handshake_receipt_sha256,
            "consumption_sha256": consumption.consumption_sha256,
            "attestation_nonces": request.attestation_nonces,
            "submission_state": "submission_uncertain",
            "automatic_retry": False,
            "reconcile_only_if_uncertain": True,
            "_seal": _RESERVED_ATTEMPT_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if (
            self._seal is not _RESERVED_ATTEMPT_TOKEN
            or self.submission_state != "submission_uncertain"
            or self.automatic_retry is not False
            or self.reconcile_only_if_uncertain is not True
        ):
            raise LegacyAdapterIntegrationError("reserved legacy attempt seal/state is invalid")


@dataclass(frozen=True, slots=True)
class LegacyAdapterDispatch:
    reservation: ReservedLegacyAttempt
    adapter_result: object


def _digest(value: Mapping[str, Any]) -> str:
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _owner() -> Any:
    global _OWNER_MODULE
    with _OWNER_LOCK:
        if _OWNER_MODULE is None:
            _OWNER_MODULE = _load_repository_owner(
                "transport_authority_closure.py",
                "transport_authority_closure",
            )
        return _OWNER_MODULE


def _fixed_adapter() -> object:
    """Resolve the sole backend through the PR4A facade without a selector."""

    import execution_facade

    return execution_facade.backend().transport


def replay_successor_readiness(
    artifacts: SuccessorAuthorityArtifacts,
    *,
    now: str | datetime,
) -> tuple[str, str, tuple[str, ...], str, str]:
    """Replay the complete successor and return only exact binding digests."""

    snapshot = artifacts.owner_snapshot()
    with _OWNER_LOCK:
        owner = _owner()
        closure = owner.validate_successor_closure(
            successor_request=snapshot["successor_request"],
            successor_authorization=snapshot["successor_authorization"],
            base_request=snapshot["base_request"],
            base_authorization=snapshot["base_authorization"],
            profile_v1=snapshot["profile_v1"],
            profile_v2=snapshot["profile_v2"],
            identity_binding=snapshot["identity_binding"],
            now=now,
        )
        receipt = owner.validate_handshake_authority_binding(
            successor_closure=closure,
            request=snapshot["handshake_request"],
            observation=snapshot["handshake_observation"],
            receipt=snapshot["handshake_receipt"],
            first_hop_request=snapshot["first_hop_request"],
            first_hop_receipt=snapshot["first_hop_receipt"],
            nested_hop_request=snapshot["nested_hop_request"],
            nested_hop_receipt=snapshot["nested_hop_receipt"],
            now=now,
        )
    authorization = snapshot["successor_authorization"]
    operations = authorization["identity_attestation"]["operations"]
    nonces = tuple(operation["request_nonce"] for operation in operations)
    readiness = _digest({
        "schema": "auto-g16-legacy-adapter-readiness/1",
        "successor_closure_sha256": closure.payload_sha256,
        "handshake_receipt_sha256": receipt["receipt_payload_sha256"],
        "authorization_sha256": authorization["authorization_payload_sha256"],
        "request_sha256": snapshot["successor_request"]["request_payload_sha256"],
        "profile_sha256": snapshot["profile_v2"]["profile_payload_sha256"],
        "identity_binding_sha256": snapshot["identity_binding"]["binding_payload_sha256"],
        "attestation_nonces": list(nonces),
        "offline_validation_only": True,
        "actual_adapter_verified": False,
    })
    return (
        authorization["authorization_id"],
        authorization["authorization_payload_sha256"],
        nonces,
        receipt["receipt_payload_sha256"],
        readiness,
    )


class LegacyAdapterIntegrator:
    """Replay, reserve, and call the one fixed adapter with no retry."""

    def __init__(
        self,
        state_owner: TrustedAuthorizationStateOwner,
        *,
        _factory_token: object,
    ) -> None:
        if _factory_token is not _INTEGRATION_FACTORY_TOKEN:
            raise TypeError("LegacyAdapterIntegrator must use a fixed production or test factory")
        self._adapter = _fixed_adapter()
        self._state_owner = state_owner

    @classmethod
    def production(cls) -> "LegacyAdapterIntegrator":
        return cls(
            TrustedAuthorizationStateOwner(),
            _factory_token=_INTEGRATION_FACTORY_TOKEN,
        )

    @classmethod
    def for_testing(
        cls,
        state_root: Path,
    ) -> "LegacyAdapterIntegrator":
        return cls(
            TrustedAuthorizationStateOwner.for_testing(state_root),
            _factory_token=_INTEGRATION_FACTORY_TOKEN,
        )

    def invoke_once(
        self,
        *,
        artifacts: SuccessorAuthorityArtifacts,
        attempt: LegacyAttemptBinding,
        now: str | datetime,
    ) -> LegacyAdapterDispatch:
        (
            authorization_id,
            authorization_sha256,
            nonces,
            handshake_receipt_sha256,
            readiness_sha256,
        ) = replay_successor_readiness(artifacts, now=now)
        request = ConsumptionRequest(
            authorization_id=authorization_id,
            authorization_sha256=authorization_sha256,
            readiness_sha256=readiness_sha256,
            attempt_id=attempt.attempt_id,
            idempotency_key_sha256=attempt.idempotency_key_sha256,
            attestation_nonces=nonces,
            consumed_at=attempt.consumed_at,
        )

        def replay_under_lock(_snapshot: dict[str, tuple[str, ...]]) -> str:
            replayed = replay_successor_readiness(artifacts, now=now)
            if replayed[:4] != (
                authorization_id,
                authorization_sha256,
                nonces,
                handshake_receipt_sha256,
            ):
                raise LegacyAdapterIntegrationError(
                    "current successor owner replay differs before reservation"
                )
            return replayed[4]

        consumption = self._state_owner.consume_after_replay(request, replay_under_lock)
        reserved = ReservedLegacyAttempt._from_consumption(
            consumption=consumption,
            request=request,
            handshake_receipt_sha256=handshake_receipt_sha256,
            token=_RESERVED_ATTEMPT_TOKEN,
        )
        reserved.assert_owner_sealed()
        try:
            result = self._adapter.invoke_reserved_once(reserved)
        except Exception as exc:
            raise LegacyAdapterInvocationUncertain(
                "legacy adapter invocation is uncertain; reservation is retained and only "
                "the existing read-only reconciliation path may continue",
                reserved,
            ) from exc
        return LegacyAdapterDispatch(reserved, result)
