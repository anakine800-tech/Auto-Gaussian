"""Version 1 JSON DTOs. These values are presentation data, never authority."""

from __future__ import annotations

from typing import Literal, TypedDict

QUERY_SCHEMA = "auto-g16-query/1"


class FieldDTO(TypedDict):
    availability: Literal["available", "missing", "unavailable"]
    value: object
    source: str | None
    reason: str | None


class QueryDTO(TypedDict):
    schema: str
    kind: str
    data: dict[str, object]


class QueryError(ValueError):
    """A bounded, path-free error suitable for CLI or future HTTP mapping."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
