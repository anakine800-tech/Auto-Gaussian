"""Application query: acquire a public Core snapshot, return the Result DTO.

No HTTP dependency, private domain imports, parsing, SQL or store mutation.
The Result owner's availability is distinct from HTTP/source access failures.
"""

from pathlib import Path
import sqlite3

from auto_g16.core import (
    CoreValidationError, RecordNotFoundError, RuntimeStoreError, SQLiteRuntimeStore,
)
from auto_g16.query import QueryError
from auto_g16.result import GaussianResultQuery


class ResultSummaryQuery:
    def __init__(self, database: str | Path):
        self.database = database

    def get_summary(self, attempt_id: str) -> dict[str, object]:
        if not isinstance(attempt_id, str) or not attempt_id or attempt_id.strip() != attempt_id:
            raise QueryError("invalid-id")
        try:
            with SQLiteRuntimeStore.read_snapshot(self.database) as store:
                # Missing HTTP resources remain 404, distinct from missing Result facts.
                store.load_attempt(attempt_id)
                dto = GaussianResultQuery(store).get_summary(attempt_id)
            # Publication follows the snapshot's final physical-source check.
            return dto
        except RecordNotFoundError:
            raise QueryError("not-found") from None
        except (RuntimeStoreError, sqlite3.Error, OSError):
            raise QueryError("store-unavailable") from None
        except (CoreValidationError, ValueError, TypeError, KeyError):
            raise QueryError("invalid-evidence") from None
