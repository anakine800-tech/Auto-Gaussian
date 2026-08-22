"""ScientificValidation-owned append-only SQLite schema version 1."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import cast

from .models import (
    MinimumValidationOutcome,
    ScientificAcceptance,
    ScientificValidationConflictError,
    ScientificValidationError,
    ScientificValidationPersistenceIntegrityError,
    _payload_text,
)


_APPLICATION_ID = 0x41334753
_USER_VERSION = 1
_SCHEMA_STATEMENTS = (
    """CREATE TABLE minimum_validations (
        minimum_validation_outcome_id TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""",
    """CREATE TABLE scientific_acceptances (
        scientific_acceptance_id TEXT PRIMARY KEY,
        minimum_validation_outcome_id TEXT NOT NULL REFERENCES minimum_validations(minimum_validation_outcome_id),
        payload_json TEXT NOT NULL
    )""",
)


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ScientificValidationPersistenceIntegrityError(
                f"duplicate JSON key is forbidden: {key!r}"
            )
        value[key] = item
    return value


def _decode_json(payload_text: object) -> dict[str, object]:
    if not isinstance(payload_text, str):
        raise ScientificValidationPersistenceIntegrityError(
            "ScientificValidation payload must be JSON text"
        )
    try:
        value = json.loads(payload_text, object_pairs_hook=_json_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScientificValidationPersistenceIntegrityError(
            "ScientificValidation payload is not exact JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ScientificValidationPersistenceIntegrityError(
            "ScientificValidation payload must be an object"
        )
    return value


def _decode_outcome(payload_text: object) -> MinimumValidationOutcome:
    payload = _decode_json(payload_text)
    record = MinimumValidationOutcome._from_payload(payload)
    if _payload_text(record) != payload_text:
        raise ScientificValidationPersistenceIntegrityError(
            "minimum validation row is not canonical"
        )
    return record


def _decode_acceptance(payload_text: object) -> ScientificAcceptance:
    payload = _decode_json(payload_text)
    record = ScientificAcceptance._from_payload(payload)
    if _payload_text(record) != payload_text:
        raise ScientificValidationPersistenceIntegrityError(
            "scientific acceptance row is not canonical"
        )
    return record


def _schema_identity(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT GLOB 'sqlite_*' ORDER BY type,name"
        )
    )


def _expected_schema_identity() -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)
        return _schema_identity(connection)
    finally:
        connection.close()


class SQLiteScientificValidationStore:
    """Opaque append-only ScientificValidation store."""

    __slots__ = ("_closed", "_connection", "_database_path", "_file_identity")

    def __init__(self) -> None:
        raise TypeError(
            "use SQLiteScientificValidationStore.create_new or open_existing"
        )

    @classmethod
    def create_new(cls, path: str | Path) -> SQLiteScientificValidationStore:
        database_path = cls._canonical_path(path)
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(database_path, flags, 0o600)
        except OSError as exc:
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation store target could not be created exclusively"
            ) from exc
        try:
            os.fchmod(descriptor, 0o600)
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode):
                raise ScientificValidationPersistenceIntegrityError(
                    "ScientificValidation store target is not a regular file"
                )
            identity = (observed.st_dev, observed.st_ino)
        finally:
            os.close(descriptor)
        store = cls._connect(database_path, identity)
        try:
            with store._transaction(immediate=True) as connection:
                if connection.execute("PRAGMA user_version").fetchone()[0] != 0:
                    raise ScientificValidationPersistenceIntegrityError(
                        "new ScientificValidation store is already versioned"
                    )
                if _schema_identity(connection):
                    raise ScientificValidationPersistenceIntegrityError(
                        "new ScientificValidation store is not empty"
                    )
                connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {_USER_VERSION}")
                for statement in _SCHEMA_STATEMENTS:
                    connection.execute(statement)
                store._attest(connection)
        except Exception:
            store.close()
            raise
        return store

    @classmethod
    def open_existing(cls, path: str | Path) -> SQLiteScientificValidationStore:
        database_path = cls._canonical_path(path)
        try:
            observed = os.lstat(database_path)
        except FileNotFoundError as exc:
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation store target is missing"
            ) from exc
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation store target must be a regular non-symlink file"
            )
        store = cls._connect(
            database_path, (observed.st_dev, observed.st_ino)
        )
        try:
            with store._transaction(immediate=False) as connection:
                store._attest(connection)
        except Exception:
            store.close()
            raise
        return store

    @staticmethod
    def _canonical_path(path: str | Path) -> Path:
        value = Path(path).expanduser()
        if not value.is_absolute():
            value = Path.cwd() / value
        # Preserve the lexical terminal component until lstat rejects aliases.
        return Path(os.path.abspath(os.fspath(value)))

    @classmethod
    def _connect(
        cls, path: Path, identity: tuple[int, int]
    ) -> SQLiteScientificValidationStore:
        store = object.__new__(cls)
        object.__setattr__(store, "_closed", True)
        object.__setattr__(store, "_database_path", path)
        object.__setattr__(store, "_file_identity", identity)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"{path.as_uri()}?mode=rw&cache=private",
                uri=True,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA read_uncommitted = OFF")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA busy_timeout = 250")
            object.__setattr__(store, "_connection", connection)
            object.__setattr__(store, "_closed", False)
            store._assert_file_identity()
        except Exception as exc:
            if connection is not None:
                connection.close()
            if isinstance(exc, ScientificValidationError):
                raise
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation store could not be opened safely"
            ) from exc
        return store

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def _assert_file_identity(self) -> None:
        try:
            observed = os.lstat(self._database_path)
        except FileNotFoundError as exc:
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation store path disappeared"
            ) from exc
        if (
            stat.S_ISLNK(observed.st_mode)
            or not stat.S_ISREG(observed.st_mode)
            or (observed.st_dev, observed.st_ino) != self._file_identity
        ):
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation store path identity changed"
            )

    def _db(self) -> sqlite3.Connection:
        if self._closed:
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation store is closed"
            )
        self._assert_file_identity()
        return self._connection

    @contextmanager
    def _transaction(self, *, immediate: bool) -> Iterator[sqlite3.Connection]:
        connection = self._db()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation SQLite operation failed"
            ) from exc
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _attest(
        self, connection: sqlite3.Connection
    ) -> tuple[
        dict[str, MinimumValidationOutcome],
        dict[str, ScientificAcceptance],
    ]:
        self._assert_file_identity()
        databases = tuple(tuple(row) for row in connection.execute("PRAGMA database_list"))
        if (
            not databases
            or databases[0][0:2] != (0, "main")
            or any(row not in {(1, "temp", "")} for row in databases[1:])
        ):
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation connection has an unexpected database"
            )
        if len(databases) == 2 and tuple(connection.execute("SELECT * FROM temp.sqlite_schema")):
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation connection has unexpected temp schema objects"
            )
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation foreign keys are disabled"
            )
        if (
            connection.execute("PRAGMA application_id").fetchone()[0]
            != _APPLICATION_ID
            or connection.execute("PRAGMA user_version").fetchone()[0]
            != _USER_VERSION
        ):
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation database header is not exact schema version 1"
            )
        if _schema_identity(connection) != _expected_schema_identity():
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation schema identity is not exact version 1"
            )
        if tuple(row[0] for row in connection.execute("PRAGMA integrity_check")) != ("ok",):
            raise ScientificValidationPersistenceIntegrityError(
                "ScientificValidation store failed integrity_check"
            )

        outcomes: dict[str, MinimumValidationOutcome] = {}
        for row in connection.execute(
            "SELECT minimum_validation_outcome_id,attempt_id,payload_json "
            "FROM minimum_validations ORDER BY rowid"
        ):
            record = _decode_outcome(row["payload_json"])
            if (
                row["minimum_validation_outcome_id"]
                != record.minimum_validation_outcome_id
                or row["attempt_id"] != record.attempt_id
                or record.minimum_validation_outcome_id in outcomes
            ):
                raise ScientificValidationPersistenceIntegrityError(
                    "minimum validation row authority is spliced or duplicated"
                )
            outcomes[record.minimum_validation_outcome_id] = record

        acceptances: dict[str, ScientificAcceptance] = {}
        for row in connection.execute(
            "SELECT scientific_acceptance_id,minimum_validation_outcome_id,payload_json "
            "FROM scientific_acceptances ORDER BY rowid"
        ):
            record = _decode_acceptance(row["payload_json"])
            outcome = outcomes.get(record.minimum_validation_outcome_id)
            if (
                row["scientific_acceptance_id"] != record.scientific_acceptance_id
                or row["minimum_validation_outcome_id"]
                != record.minimum_validation_outcome_id
                or record.scientific_acceptance_id in acceptances
                or outcome is None
                or record.classification.value != "VALIDATED_MINIMUM"
                or (
                    record.validation_policy_id,
                    record.validation_policy_version,
                    record.calculation_plan_id,
                    record.calculation_plan_revision,
                    record.attempt_id,
                    record.parse_result_id,
                    record.classification,
                )
                != (
                    outcome.validation_policy_id,
                    outcome.validation_policy_version,
                    outcome.calculation_plan_id,
                    outcome.calculation_plan_revision,
                    outcome.attempt_id,
                    outcome.parse_result_id,
                    outcome.classification,
                )
            ):
                raise ScientificValidationPersistenceIntegrityError(
                    "scientific acceptance row authority is invalid"
                )
            acceptances[record.scientific_acceptance_id] = record
        return outcomes, acceptances

    def _append(
        self,
        *,
        table: str,
        identity_column: str,
        identity: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
    ) -> None:
        with self._transaction(immediate=True) as connection:
            before = self._attest(connection)
            existing = connection.execute(
                f"SELECT {','.join(columns)} FROM {table} "
                f"WHERE {identity_column} = ?",
                (identity,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) == values:
                    if self._attest(connection) != before:
                        raise ScientificValidationPersistenceIntegrityError(
                            "idempotent replay changed ScientificValidation persistence"
                        )
                    return
                raise ScientificValidationConflictError(
                    f"ScientificValidation identity {identity!r} has different content"
                )
            try:
                cursor = connection.execute(
                    f"INSERT OR ABORT INTO {table} ({','.join(columns)}) "
                    f"VALUES ({','.join('?' for _ in values)})",
                    values,
                )
            except sqlite3.IntegrityError as exc:
                raise ScientificValidationConflictError(
                    "ScientificValidation append conflicts with immutable authority"
                ) from exc
            if cursor.rowcount != 1 or connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ScientificValidationPersistenceIntegrityError(
                    "ScientificValidation append did not write exactly one row"
                )
            after = self._attest(connection)
            if (
                len(after[0]) + len(after[1])
                != len(before[0]) + len(before[1]) + 1
            ):
                raise ScientificValidationPersistenceIntegrityError(
                    "ScientificValidation append changed unexpected rows"
                )

    def _record_minimum_validation(self, record: MinimumValidationOutcome) -> None:
        if not isinstance(record, MinimumValidationOutcome):
            raise ScientificValidationError("record must be a MinimumValidationOutcome")
        payload = _payload_text(record)
        try:
            _decode_outcome(payload)
        except ScientificValidationPersistenceIntegrityError as exc:
            raise ScientificValidationConflictError(
                "MinimumValidationOutcome identity does not close over supplied content"
            ) from exc
        self._append(
            table="minimum_validations",
            identity_column="minimum_validation_outcome_id",
            identity=record.minimum_validation_outcome_id,
            columns=("minimum_validation_outcome_id", "attempt_id", "payload_json"),
            values=(record.minimum_validation_outcome_id, record.attempt_id, payload),
        )

    def _record_scientific_acceptance(self, record: ScientificAcceptance) -> None:
        if not isinstance(record, ScientificAcceptance):
            raise ScientificValidationError("record must be a ScientificAcceptance")
        payload = _payload_text(record)
        try:
            _decode_acceptance(payload)
        except ScientificValidationPersistenceIntegrityError as exc:
            raise ScientificValidationConflictError(
                "ScientificAcceptance identity does not close over supplied content"
            ) from exc
        self._append(
            table="scientific_acceptances",
            identity_column="scientific_acceptance_id",
            identity=record.scientific_acceptance_id,
            columns=(
                "scientific_acceptance_id",
                "minimum_validation_outcome_id",
                "payload_json",
            ),
            values=(
                record.scientific_acceptance_id,
                record.minimum_validation_outcome_id,
                payload,
            ),
        )

    def load_minimum_validation(
        self, outcome_id: str
    ) -> MinimumValidationOutcome:
        with self._transaction(immediate=False) as connection:
            outcomes, _acceptances = self._attest(connection)
            try:
                return outcomes[outcome_id]
            except KeyError as exc:
                raise ScientificValidationError(
                    f"minimum validation {outcome_id!r} was not found"
                ) from exc

    def load_scientific_acceptance(
        self, acceptance_id: str
    ) -> ScientificAcceptance:
        with self._transaction(immediate=False) as connection:
            _outcomes, acceptances = self._attest(connection)
            try:
                return acceptances[acceptance_id]
            except KeyError as exc:
                raise ScientificValidationError(
                    f"scientific acceptance {acceptance_id!r} was not found"
                ) from exc

    def minimum_validations_for_attempt(
        self, attempt_id: str
    ) -> tuple[MinimumValidationOutcome, ...]:
        with self._transaction(immediate=False) as connection:
            self._attest(connection)
            rows = connection.execute(
                "SELECT payload_json FROM minimum_validations "
                "WHERE attempt_id = ? ORDER BY rowid",
                (attempt_id,),
            ).fetchall()
            return tuple(_decode_outcome(row[0]) for row in rows)

    def acceptances_for_outcome(
        self, outcome_id: str
    ) -> tuple[ScientificAcceptance, ...]:
        with self._transaction(immediate=False) as connection:
            self._attest(connection)
            rows = connection.execute(
                "SELECT payload_json FROM scientific_acceptances "
                "WHERE minimum_validation_outcome_id = ? ORDER BY rowid",
                (outcome_id,),
            ).fetchall()
            return tuple(_decode_acceptance(row[0]) for row in rows)
