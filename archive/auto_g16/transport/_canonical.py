"""Private canonical encoding and deterministic Transport identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from typing import Final
from uuid import UUID, uuid5


_ROOT_NAMESPACE: Final = UUID("6e54140f-f4e7-5482-a6c1-8f5729e3c112")
_SCHEDULER_NAMESPACE: Final = UUID("b863c565-aa1b-5ea9-8c9e-170dc7af33c6")
_CAPTURE_NAMESPACE: Final = UUID("8ea6ba6d-0365-5493-9bda-87f4be9f23a8")
_STORE_NAMESPACE: Final = UUID("08b51475-e12f-5c8a-9c29-ac1a50c4778d")
_STORE_INSTANCE_NAMESPACE: Final = UUID("10b04ccd-414d-502e-a23b-8347087797fd")
_RUNTIME_NAMESPACE: Final = UUID("4fd2e62a-471b-5cdf-a41c-c73cd15df6be")
_WORKSPACE_NAMESPACE: Final = UUID("cf5d20c0-dcf7-5017-b550-a4b86d2e2315")
_ARTIFACT_NAMESPACE: Final = UUID("1bb613c9-3d29-584e-a061-ba3bf03589b5")
_JOB_NAMESPACE: Final = UUID("d82d6457-637e-5262-8741-d721d2b5057f")
_RECEIPT_NAMESPACE: Final = UUID("26685dd2-091e-5476-9556-1b6416d6a200")


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


def canonical_json_bytes(value: object) -> bytes:
    """Encode the frozen manifest/bootstrap canonical JSON grammar."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise TransportBoundaryError("value is not canonical JSON") from exc


def strict_canonical_json(raw: bytes, field_name: str) -> object:
    """Parse one canonical JSON object/value with duplicate-key rejection."""

    if type(raw) is not bytes or raw.startswith(b"\xef\xbb\xbf"):
        raise TransportBoundaryError(f"{field_name} must be UTF-8 without BOM")
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise TransportBoundaryError(f"{field_name} must have exactly one trailing LF")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise TransportBoundaryError(f"{field_name} contains a duplicate key")
            value[key] = item
        return value

    def nonfinite(value: str) -> object:
        raise TransportBoundaryError(f"{field_name} contains {value}")

    try:
        decoded = raw.decode("utf-8")
        value = json.loads(decoded, object_pairs_hook=pairs, parse_constant=nonfinite)
    except TransportBoundaryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportBoundaryError(f"{field_name} is not strict JSON") from exc
    if canonical_json_bytes(value) != raw:
        raise TransportBoundaryError(f"{field_name} is not canonical JSON")
    return value


_IDENTITY_NAMESPACES: Final = {
    "transport-store": _STORE_NAMESPACE,
    "store-instance": _STORE_INSTANCE_NAMESPACE,
    "runtime-attestation": _RUNTIME_NAMESPACE,
    "workspace-physical": _WORKSPACE_NAMESPACE,
    "artifact-physical": _ARTIFACT_NAMESPACE,
    "job-physical": _JOB_NAMESPACE,
    "receipt-binding": _RECEIPT_NAMESPACE,
}


def physical_id(domain: str, payload: object) -> str:
    try:
        namespace = _IDENTITY_NAMESPACES[domain]
    except KeyError as exc:
        raise TransportBoundaryError("unknown Transport identity domain") from exc
    return str(uuid5(namespace, canonical_bytes(payload).decode("ascii")))


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
    "canonical_json_bytes",
    "capture_id",
    "digest",
    "physical_id",
    "scheduler_id",
    "strict_canonical_json",
]
