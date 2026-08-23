"""Private canonical encoding and deterministic Transport identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Final
from uuid import UUID, uuid5


_ROOT_NAMESPACE: Final = UUID("6e54140f-f4e7-5482-a6c1-8f5729e3c112")
_SCHEDULER_NAMESPACE: Final = UUID("b863c565-aa1b-5ea9-8c9e-170dc7af33c6")
_CAPTURE_NAMESPACE: Final = UUID("8ea6ba6d-0365-5493-9bda-87f4be9f23a8")


class TransportBoundaryError(ValueError):
    """Transport evidence is malformed, stale, unsafe, or cross-spliced."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TransportBoundaryError(
            f"{field_name} must be a non-empty string without surrounding whitespace"
        )
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise TransportBoundaryError(f"{field_name} contains a forbidden character")
    return value


def _positive(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TransportBoundaryError(f"{field_name} must be a positive integer")
    return value


def _sha256(value: object, field_name: str) -> str:
    _text(value, field_name)
    assert isinstance(value, str)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise TransportBoundaryError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def canonical_bytes(value: object) -> bytes:
    """Encode the frozen tagged canonical Transport grammar."""

    if value is None:
        return b"n;"
    if type(value) is bool:
        return b"b1;" if value else b"b0;"
    if type(value) is int:
        return b"i" + str(value).encode("ascii") + b";"
    if type(value) is str:
        if any(character in value for character in ("\x00", "\r", "\n")):
            raise TransportBoundaryError("canonical string contains a forbidden character")
        encoded = value.encode("utf-8")
        return b"s" + str(len(encoded)).encode("ascii") + b":" + encoded
    if type(value) is bytes:
        return b"y" + str(len(value)).encode("ascii") + b":" + value.hex().encode("ascii")
    if isinstance(value, Mapping):
        keys = tuple(value)
        if any(type(key) is not str for key in keys):
            raise TransportBoundaryError("canonical object keys must be strings")
        ordered = tuple(sorted(keys, key=lambda item: item.encode("utf-8")))
        return (
            b"o"
            + str(len(ordered)).encode("ascii")
            + b":"
            + b"".join(canonical_bytes(key) + canonical_bytes(value[key]) for key in ordered)
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return (
            b"a"
            + str(len(value)).encode("ascii")
            + b":"
            + b"".join(canonical_bytes(item) for item in value)
        )
    raise TransportBoundaryError(
        f"canonical value type {type(value).__name__} is not supported"
    )


def scheduler_id(name_payload: object) -> str:
    return str(uuid5(_SCHEDULER_NAMESPACE, canonical_bytes(name_payload).decode("ascii")))


def capture_id(name_payload: object) -> str:
    return str(uuid5(_CAPTURE_NAMESPACE, canonical_bytes(name_payload).decode("ascii")))


def digest(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


__all__ = [
    "TransportBoundaryError",
    "_CAPTURE_NAMESPACE",
    "_ROOT_NAMESPACE",
    "_SCHEDULER_NAMESPACE",
    "_positive",
    "_sha256",
    "_text",
    "canonical_bytes",
    "capture_id",
    "digest",
    "scheduler_id",
]
