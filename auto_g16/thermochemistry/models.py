"""The single public V31 thermochemistry record."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
from math import isfinite
from types import MappingProxyType


def _freeze(value: object, path: str, active: set[int] | None = None) -> object:
    containers = set() if active is None else active
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError(f"{path} must not contain a non-finite float")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in containers:
            raise ValueError(f"{path} must not contain a container cycle")
        containers.add(identity)
        try:
            if any(not isinstance(key, str) or not key or key != key.strip() for key in value):
                raise ValueError(f"{path} keys must be non-empty canonical strings")
            return MappingProxyType(
                {key: _freeze(value[key], f"{path}.{key}", containers) for key in sorted(value)}
            )
        finally:
            containers.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in containers:
            raise ValueError(f"{path} must not contain a container cycle")
        containers.add(identity)
        try:
            return tuple(
                _freeze(item, f"{path}[{index}]", containers) for index, item in enumerate(value)
            )
        finally:
            containers.remove(identity)
    raise ValueError(f"{path} contains unsupported value type {type(value).__name__}")


def _freeze_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    frozen = _freeze(value, path)
    assert isinstance(frozen, Mapping)
    return frozen


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_value(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain_value(item) for item in value]
    return value


def _payload_sha256(value: object) -> str:
    encoded = json.dumps(
        _plain_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identified_payload(domain: str, payload: Mapping[str, object]) -> tuple[str, str]:
    digest = _payload_sha256({"domain": domain, "payload": payload})
    return f"{domain}-{digest}", _payload_sha256(payload)


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ThermodynamicEnsemble:
    """One immutable, complete thermodynamic aggregation of an eligible conformer set."""

    schema_version: int
    thermodynamic_ensemble_id: str = field(init=False)
    payload_sha256: str = field(init=False)
    conformer_ensemble_id: str
    conformer_ensemble_payload_sha256: str
    source_member_ids: tuple[str, ...]
    temperature_k: float
    standard_state: str
    standard_state_binding: Mapping[str, object]
    gas_constant_binding: Mapping[str, object]
    thermochemistry_policy_id: str
    thermochemistry_policy_payload_sha256: str
    thermochemistry_policy: Mapping[str, object]
    goodvibes_implementation_id: str
    goodvibes_implementation_binding: Mapping[str, object]
    low_frequency_treatment: Mapping[str, object]
    method_compatibility_id: str
    method_compatibility_binding: Mapping[str, object]
    member_observations: tuple[Mapping[str, object], ...]
    partition_evidence: Mapping[str, object]
    population_normalization: Mapping[str, object]
    ensemble_treated_free_energy_hartree: float

    def __init__(self) -> None:
        raise TypeError("ThermodynamicEnsemble is service-created")

    @classmethod
    def _create(cls, **fields: object) -> ThermodynamicEnsemble:
        value = object.__new__(cls)
        object.__setattr__(value, "schema_version", 1)
        for name in (
            "conformer_ensemble_id",
            "conformer_ensemble_payload_sha256",
            "source_member_ids",
            "temperature_k",
            "standard_state",
            "thermochemistry_policy_id",
            "thermochemistry_policy_payload_sha256",
            "goodvibes_implementation_id",
            "method_compatibility_id",
            "ensemble_treated_free_energy_hartree",
        ):
            object.__setattr__(value, name, fields[name])
        for name in (
            "standard_state_binding",
            "gas_constant_binding",
            "thermochemistry_policy",
            "goodvibes_implementation_binding",
            "low_frequency_treatment",
            "method_compatibility_binding",
            "partition_evidence",
            "population_normalization",
        ):
            object.__setattr__(value, name, _freeze_mapping(fields[name], name))
        members = _freeze(fields["member_observations"], "member_observations")
        assert isinstance(members, tuple) and all(isinstance(item, Mapping) for item in members)
        object.__setattr__(value, "member_observations", members)
        ensemble_id, payload_hash = _identified_payload(
            "thermodynamic-ensemble", value._identity_payload()
        )
        object.__setattr__(value, "thermodynamic_ensemble_id", ensemble_id)
        object.__setattr__(value, "payload_sha256", payload_hash)
        return value

    def _identity_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "conformer_ensemble_id": self.conformer_ensemble_id,
            "conformer_ensemble_payload_sha256": self.conformer_ensemble_payload_sha256,
            "source_member_ids": self.source_member_ids,
            "temperature_k": self.temperature_k,
            "standard_state": self.standard_state,
            "standard_state_binding": self.standard_state_binding,
            "gas_constant_binding": self.gas_constant_binding,
            "thermochemistry_policy_id": self.thermochemistry_policy_id,
            "thermochemistry_policy_payload_sha256": self.thermochemistry_policy_payload_sha256,
            "thermochemistry_policy": self.thermochemistry_policy,
            "goodvibes_implementation_id": self.goodvibes_implementation_id,
            "goodvibes_implementation_binding": self.goodvibes_implementation_binding,
            "low_frequency_treatment": self.low_frequency_treatment,
            "method_compatibility_id": self.method_compatibility_id,
            "method_compatibility_binding": self.method_compatibility_binding,
            "member_observations": self.member_observations,
            "partition_evidence": self.partition_evidence,
            "population_normalization": self.population_normalization,
            "ensemble_treated_free_energy_hartree": self.ensemble_treated_free_energy_hartree,
        }
