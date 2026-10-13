"""Trusted private single-use state for v2.6 execution authorization.

This owner is local-only.  It never accepts a caller registry and never
performs transport, scheduler, Gaussian, cancellation, or cleanup work.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


AUTHORIZATION_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
ATTEMPT_ID_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
NONCE_RE = re.compile(r"^[a-f0-9]{32,128}$")
STATE_SCHEMA = "auto-g16-trusted-execution-consumption/1"
_TEST_OWNER_FACTORY_TOKEN = object()
_TEST_CLOCK_FACTORY_TOKEN = object()


class AuthorizationStateError(ValueError):
    """Trusted authorization state is unavailable, inconsistent, or used."""


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _validate_component(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AuthorizationStateError(f"{label} is malformed")
    return value


def _validate_consumption_identity(request: object) -> None:
    authorization_id = getattr(request, "authorization_id", None)
    attempt_id = getattr(request, "attempt_id", None)
    _validate_component(authorization_id, AUTHORIZATION_ID_RE, "authorization_id")
    _validate_component(attempt_id, ATTEMPT_ID_RE, "attempt_id")
    for label in (
        "authorization_sha256",
        "readiness_sha256",
        "idempotency_key_sha256",
    ):
        _validate_component(getattr(request, label, None), SHA256_RE, label)
    attestation_nonces = getattr(request, "attestation_nonces", None)
    if (
        not isinstance(attestation_nonces, tuple)
        or not attestation_nonces
        or len(set(attestation_nonces)) != len(attestation_nonces)
    ):
        raise AuthorizationStateError("attestation nonces must be non-empty and unique")
    for nonce in attestation_nonces:
        _validate_component(nonce, NONCE_RE, "attestation nonce")


@dataclass(frozen=True, slots=True)
class ConsumptionIntent:
    """Untimed reservation identity for the trusted-current-time owner path."""

    authorization_id: str
    authorization_sha256: str
    readiness_sha256: str
    attempt_id: str
    idempotency_key_sha256: str
    attestation_nonces: tuple[str, ...]

    def validate(self) -> None:
        _validate_consumption_identity(self)


@dataclass(frozen=True, slots=True)
class ConsumptionRequest:
    authorization_id: str
    authorization_sha256: str
    readiness_sha256: str
    attempt_id: str
    idempotency_key_sha256: str
    attestation_nonces: tuple[str, ...]
    consumed_at: str

    def validate(self) -> None:
        _validate_consumption_identity(self)
        if not isinstance(self.consumed_at, str) or not self.consumed_at.endswith("Z"):
            raise AuthorizationStateError("consumed_at must be explicit UTC")


@dataclass(frozen=True, slots=True)
class ConsumedAuthorization:
    authorization_id: str
    attempt_id: str
    consumption_sha256: str
    consumed: bool = True
    submission_state: str = "submission_uncertain"


@dataclass(frozen=True, slots=True)
class TrustedTimeConsumedAuthorization:
    authorization_id: str
    attempt_id: str
    consumption_sha256: str
    consumed_at: str
    consumed: bool = True
    submission_state: str = "submission_uncertain"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_state_root() -> Path:
    return Path.home() / ".config" / "auto-g16" / "execution-authority-state"


def _canonical_clock_value(clock: Callable[[], datetime]) -> tuple[datetime, str]:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AuthorizationStateError("trusted clock must return timezone-aware UTC")
    canonical = value.astimezone(timezone.utc)
    return canonical, canonical.isoformat().replace("+00:00", "Z")


class TrustedAuthorizationStateOwner:
    """Locked, no-clobber owner of the one-time authorization namespace."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        _factory_token: object | None = None,
        _clock: Callable[[], datetime] | None = None,
        _clock_token: object | None = None,
    ) -> None:
        if root is not None and _factory_token is not _TEST_OWNER_FACTORY_TOKEN:
            raise AuthorizationStateError("production state root is fixed and has no caller override")
        if _clock is not None and _clock_token is not _TEST_CLOCK_FACTORY_TOKEN:
            raise AuthorizationStateError("production owner clock is fixed")
        self._root = (root if root is not None else _default_state_root()).absolute()
        self._clock = _clock if _clock is not None else _utc_now

    @classmethod
    def for_testing(cls, root: Path) -> "TrustedAuthorizationStateOwner":
        return cls(root, _factory_token=_TEST_OWNER_FACTORY_TOKEN)

    @classmethod
    def _for_testing_with_clock(
        cls,
        root: Path,
        clock: Callable[[], datetime],
        *,
        _test_token: object,
    ) -> "TrustedAuthorizationStateOwner":
        if _test_token is not _TEST_CLOCK_FACTORY_TOKEN:
            raise AuthorizationStateError("private test clock factory token differs")
        return cls(
            root,
            _factory_token=_TEST_OWNER_FACTORY_TOKEN,
            _clock=clock,
            _clock_token=_TEST_CLOCK_FACTORY_TOKEN,
        )

    def _ensure_private_directory(self, path: Path) -> None:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise AuthorizationStateError("authorization state directory is not a regular directory")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise AuthorizationStateError("authorization state directory owner differs")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise AuthorizationStateError("authorization state directory is not private")

    def _prepare(self) -> Path:
        self._ensure_private_directory(self._root)
        records = self._root / "consumptions"
        self._ensure_private_directory(records)
        return records

    @contextlib.contextmanager
    def _locked(self) -> Iterator[Path]:
        records = self._prepare()
        lock_path = self._root / "owner.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise AuthorizationStateError("authorization state lock is unsafe")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield records
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _load_records(self, records: Path) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(records.iterdir(), key=lambda item: item.name):
            if path.name.startswith(".pending-"):
                raise AuthorizationStateError("incomplete authorization publication requires reconciliation")
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise AuthorizationStateError("authorization state contains a non-regular record")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                raw = b""
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    raw += chunk
            finally:
                os.close(descriptor)
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AuthorizationStateError("authorization state record is malformed") from exc
            expected = {
                "schema", "authorization_id", "authorization_sha256", "readiness_sha256",
                "attempt_id", "idempotency_key_sha256", "attestation_nonces",
                "consumed_at", "submission_state", "automatic_retry",
                "consumption_sha256",
            }
            if not isinstance(value, dict) or set(value) != expected:
                raise AuthorizationStateError("authorization state record is not closed")
            projection = {key: item for key, item in value.items() if key != "consumption_sha256"}
            if value["schema"] != STATE_SCHEMA or value["consumption_sha256"] != _digest(projection):
                raise AuthorizationStateError("authorization state record digest differs")
            result.append(value)
        return result

    def snapshot(self) -> dict[str, tuple[str, ...]]:
        with self._locked() as records:
            loaded = self._load_records(records)
            return {
                "known_authorization_ids": tuple(sorted(item["authorization_id"] for item in loaded)),
                "consumed_authorization_ids": tuple(sorted(item["authorization_id"] for item in loaded)),
                "known_attestation_nonces": tuple(sorted({nonce for item in loaded for nonce in item["attestation_nonces"]})),
            }

    def consume_after_replay(
        self,
        request: ConsumptionRequest,
        replay: Callable[[dict[str, tuple[str, ...]]], str],
        *,
        _crash_before_publish: bool = False,
    ) -> ConsumedAuthorization:
        """Replay under the owner lock, then publish one uncertain reservation."""

        request.validate()
        with self._locked() as records:
            loaded = self._load_records(records)
            snapshot = {
                "known_authorization_ids": tuple(sorted(item["authorization_id"] for item in loaded)),
                "consumed_authorization_ids": tuple(sorted(item["authorization_id"] for item in loaded)),
                "known_attestation_nonces": tuple(sorted({nonce for item in loaded for nonce in item["attestation_nonces"]})),
            }
            if request.authorization_id in snapshot["known_authorization_ids"]:
                raise AuthorizationStateError("authorization is already consumed")
            if request.attempt_id in {item["attempt_id"] for item in loaded}:
                raise AuthorizationStateError("attempt already has an authorization reservation")
            if set(request.attestation_nonces).intersection(snapshot["known_attestation_nonces"]):
                raise AuthorizationStateError("attestation nonce is already reserved")
            replay_sha256 = replay(snapshot)
            if replay_sha256 != request.readiness_sha256:
                raise AuthorizationStateError("current owner replay differs from the requested readiness")
            projection = {
                "schema": STATE_SCHEMA,
                "authorization_id": request.authorization_id,
                "authorization_sha256": request.authorization_sha256,
                "readiness_sha256": request.readiness_sha256,
                "attempt_id": request.attempt_id,
                "idempotency_key_sha256": request.idempotency_key_sha256,
                "attestation_nonces": list(request.attestation_nonces),
                "consumed_at": request.consumed_at,
                "submission_state": "submission_uncertain",
                "automatic_retry": False,
            }
            record = {**projection, "consumption_sha256": _digest(projection)}
            final_path = records / f"{request.authorization_id}.json"
            pending_path = records / f".pending-{request.authorization_id}-{os.getpid()}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(pending_path, flags, 0o400)
            try:
                raw = _canonical_bytes(record)
                offset = 0
                while offset < len(raw):
                    offset += os.write(descriptor, raw[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if _crash_before_publish:
                raise RuntimeError("synthetic crash before authorization publication")
            try:
                os.link(pending_path, final_path, follow_symlinks=False)
            except FileExistsError as exc:
                raise AuthorizationStateError("authorization publication already exists") from exc
            os.unlink(pending_path)
            directory_descriptor = os.open(records, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            return ConsumedAuthorization(
                request.authorization_id,
                request.attempt_id,
                record["consumption_sha256"],
            )

    def consume_after_replay_at_trusted_now(
        self,
        intent: ConsumptionIntent,
        replay: Callable[[dict[str, tuple[str, ...]], datetime], str],
    ) -> TrustedTimeConsumedAuthorization:
        """Obtain trusted UTC under lock, replay, then reserve with that same UTC."""

        intent.validate()
        with self._locked() as records:
            loaded = self._load_records(records)
            snapshot = {
                "known_authorization_ids": tuple(sorted(item["authorization_id"] for item in loaded)),
                "consumed_authorization_ids": tuple(sorted(item["authorization_id"] for item in loaded)),
                "known_attestation_nonces": tuple(sorted({nonce for item in loaded for nonce in item["attestation_nonces"]})),
            }
            if intent.authorization_id in snapshot["known_authorization_ids"]:
                raise AuthorizationStateError("authorization is already consumed")
            if intent.attempt_id in {item["attempt_id"] for item in loaded}:
                raise AuthorizationStateError("attempt already has an authorization reservation")
            if set(intent.attestation_nonces).intersection(snapshot["known_attestation_nonces"]):
                raise AuthorizationStateError("attestation nonce is already reserved")
            trusted_now, consumed_at = _canonical_clock_value(self._clock)
            replay_sha256 = replay(snapshot, trusted_now)
            if replay_sha256 != intent.readiness_sha256:
                raise AuthorizationStateError("current owner replay differs from the requested readiness")
            request = ConsumptionRequest(
                authorization_id=intent.authorization_id,
                authorization_sha256=intent.authorization_sha256,
                readiness_sha256=intent.readiness_sha256,
                attempt_id=intent.attempt_id,
                idempotency_key_sha256=intent.idempotency_key_sha256,
                attestation_nonces=intent.attestation_nonces,
                consumed_at=consumed_at,
            )
            projection = {
                "schema": STATE_SCHEMA,
                "authorization_id": request.authorization_id,
                "authorization_sha256": request.authorization_sha256,
                "readiness_sha256": request.readiness_sha256,
                "attempt_id": request.attempt_id,
                "idempotency_key_sha256": request.idempotency_key_sha256,
                "attestation_nonces": list(request.attestation_nonces),
                "consumed_at": request.consumed_at,
                "submission_state": "submission_uncertain",
                "automatic_retry": False,
            }
            record = {**projection, "consumption_sha256": _digest(projection)}
            final_path = records / f"{request.authorization_id}.json"
            pending_path = records / f".pending-{request.authorization_id}-{os.getpid()}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(pending_path, flags, 0o400)
            try:
                raw = _canonical_bytes(record)
                offset = 0
                while offset < len(raw):
                    offset += os.write(descriptor, raw[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                os.link(pending_path, final_path, follow_symlinks=False)
            except FileExistsError as exc:
                raise AuthorizationStateError("authorization publication already exists") from exc
            os.unlink(pending_path)
            directory_descriptor = os.open(records, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            return TrustedTimeConsumedAuthorization(
                request.authorization_id,
                request.attempt_id,
                record["consumption_sha256"],
                request.consumed_at,
            )
