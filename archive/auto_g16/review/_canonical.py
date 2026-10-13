"""Private canonical projection and identity helpers for ReviewBundle."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import json
from math import isfinite
from uuid import UUID, uuid5


_REVIEW_NAMESPACE = UUID("061dffea-e54e-580e-9928-e284abc0997f")
_BUNDLE_NAMESPACE = UUID("62e6a827-7dbf-5efe-8625-729e43bc9d46")


class _FrozenMapping(Mapping[str, object]):
    __slots__ = ("_items",)

    def __init__(self, items: tuple[tuple[str, object], ...]) -> None:
        self._items = items

    def __getitem__(self, key: str) -> object:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return repr(dict(self._items))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return False
        try:
            return self._items == freeze_mapping(other, "mapping")._items
        except ValueError:
            return False

    def __hash__(self) -> int:
        return hash(self._items)


def freeze_value(value: object, path: str, active: set[int] | None = None) -> object:
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
            items: list[tuple[str, object]] = []
            for key, item in value.items():
                if not isinstance(key, str) or not key:
                    raise ValueError(f"{path} keys must be non-empty strings")
                items.append((key, freeze_value(item, f"{path}.{key}", containers)))
            return _FrozenMapping(tuple(sorted(items)))
        finally:
            containers.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in containers:
            raise ValueError(f"{path} must not contain a container cycle")
        containers.add(identity)
        try:
            return tuple(
                freeze_value(item, f"{path}[{index}]", containers)
                for index, item in enumerate(value)
            )
        finally:
            containers.remove(identity)
    raise ValueError(f"{path} contains unsupported value type {type(value).__name__}")


def freeze_mapping(value: object, path: str) -> _FrozenMapping:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    frozen = freeze_value(value, path)
    assert isinstance(frozen, _FrozenMapping)
    return frozen


def plain_value(value: object) -> object:
    from enum import Enum

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: plain_value(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [plain_value(item) for item in value]
    return value


def _canonical_node(value: object) -> object:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["boolean", value]
    if type(value) is int:
        return ["integer", value]
    if type(value) is float:
        if not isfinite(value):
            raise ValueError("ReviewBundle identity contains a non-finite float")
        return ["float", value]
    if type(value) is str:
        return ["string", value]
    if isinstance(value, Mapping):
        return [
            "mapping",
            [[key, _canonical_node(value[key])] for key in sorted(value)],
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ["sequence", [_canonical_node(item) for item in value]]
    raise ValueError(
        f"ReviewBundle identity contains unsupported {type(value).__name__}"
    )


def bundle_identity(payload: Mapping[str, object]) -> str:
    expected = uuid5(_REVIEW_NAMESPACE, "auto_g16.review/v1/review-bundle")
    if expected != _BUNDLE_NAMESPACE:
        raise ValueError("ReviewBundle namespace authority is inconsistent")
    canonical = json.dumps(
        _canonical_node(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    return str(uuid5(_BUNDLE_NAMESPACE, canonical))
