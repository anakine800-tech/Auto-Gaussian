"""Closed data helpers for the private offline model."""

from collections.abc import Mapping
from hashlib import sha256
import json

from auto_g16.approval.models import canonical_bytes, plain_value


class Rejected(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class RequestRejected(Rejected):
    """Audited request refusal, not an integrity or effect failure.

    Only the owner at a known pre-effect rejection site may use this marker.
    A reason string alone never establishes that classification.
    """


def exact(value, keys):
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise Rejected("BAD_FRAME")


def json_bytes(value):
    return json.dumps(plain_value(value), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return sha256(canonical_bytes(value)).hexdigest()


def copy_data(value):
    return json.loads(json_bytes(value))


def frame(value, cap):
    body = json_bytes(value)
    if not 1 <= len(body) <= cap:
        raise Rejected("BAD_FRAME")
    return len(body).to_bytes(4, "big") + body


def decode_frame(raw, cap, *, eof, ancillary=False):
    """Complete-frame model only; sockets/deadlines/FD closure are not provided."""
    if type(raw) is not bytes or not eof or ancillary or len(raw) < 5:
        raise Rejected("BAD_FRAME")
    size = int.from_bytes(raw[:4], "big")
    if not 1 <= size <= cap or len(raw) != size + 4:
        raise Rejected("BAD_FRAME")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Rejected("BAD_FRAME")
            result[key] = value
        return result

    def constant(_value):
        raise Rejected("BAD_FRAME")

    try:
        value = json.loads(raw[4:].decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
        if json_bytes(value) != raw[4:]:
            raise Rejected("BAD_FRAME")
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise Rejected("BAD_FRAME") from exc
