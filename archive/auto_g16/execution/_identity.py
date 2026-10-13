"""Private deterministic identity and immutable semantic-value helpers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from hashlib import sha256
import json
from typing import Final
from uuid import UUID, uuid5


_EXECUTION_NAMESPACE: Final = UUID("4fbc452d-47a8-5fa6-b4ef-c25de2aeb6ba")


class ExecutionValueError(ValueError):
    """An execution value does not satisfy the frozen v3 contract."""


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

    def __hash__(self) -> int:
        return hash(self._items)


def require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ExecutionValueError(
            f"{field_name} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise ExecutionValueError(f"{field_name} must not contain NUL")
    return value


def require_positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExecutionValueError(f"{field_name} must be a positive integer")
    return value


def require_sha256(value: object, field_name: str) -> str:
    require_text(value, field_name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ExecutionValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def freeze_mapping(value: Mapping[str, object], field_name: str) -> Mapping[str, object]:
    frozen = _freeze_value(value, field_name, set())
    if not isinstance(frozen, _FrozenMapping):
        raise ExecutionValueError(f"{field_name} must be a mapping")
    return frozen


def _freeze_value(value: object, path: str, active: set[int]) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ExecutionValueError(f"{path} must not contain a container cycle")
        active.add(identity)
        try:
            items: list[tuple[str, object]] = []
            for key, item in value.items():
                if not isinstance(key, str) or not key:
                    raise ExecutionValueError(f"{path} keys must be non-empty strings")
                items.append((key, _freeze_value(item, f"{path}.{key}", active)))
            return _FrozenMapping(tuple(sorted(items, key=lambda pair: pair[0])))
        finally:
            active.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in active:
            raise ExecutionValueError(f"{path} must not contain a container cycle")
        active.add(identity)
        try:
            return tuple(
                _freeze_value(item, f"{path}[{index}]", active)
                for index, item in enumerate(value)
            )
        finally:
            active.remove(identity)
    raise ExecutionValueError(
        f"{path} contains unsupported value type {type(value).__name__}"
    )


def _canonical_node(value: object) -> object:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["boolean", value]
    if type(value) is int:
        return ["integer", value]
    if type(value) is str:
        return ["string", value]
    if isinstance(value, Mapping):
        return [
            "mapping",
            [[key, _canonical_node(value[key])] for key in sorted(value)],
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ["sequence", [_canonical_node(item) for item in value]]
    raise ExecutionValueError(
        f"identity payload contains unsupported value type {type(value).__name__}"
    )


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _canonical_node(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def semantic_id(domain: str, payload: Mapping[str, object]) -> str:
    require_text(domain, "identity domain")
    name = b"auto-g16.execution\x00v1\x00" + domain.encode("utf-8") + b"\x00"
    name += canonical_bytes(payload)
    return str(uuid5(_EXECUTION_NAMESPACE, name.decode("utf-8")))


def semantic_sha256(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def bytes_identity(value: bytes) -> Mapping[str, object]:
    if not isinstance(value, bytes):
        raise ExecutionValueError("effect bytes must be immutable bytes")
    return freeze_mapping(
        {"sha256": sha256(value).hexdigest(), "size_bytes": len(value)},
        "bytes_identity",
    )
