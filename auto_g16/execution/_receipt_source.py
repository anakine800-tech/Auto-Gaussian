"""Fixed local source locator for historical proof; never a live installation."""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os

from auto_g16.transport._canonical import TransportBoundaryError
from auto_g16.transport._program_rtwin import _PublisherFileBinding, _PinnedPublisherFile
from . import _program_completion as c


@dataclass(frozen=True, slots=True)
class _FixedReceiptSource:
    snapshot_id: str
    core: _PublisherFileBinding
    transport: _PublisherFileBinding
    bootstrap_source_sha256: str
    bootstrap_source_size_bytes: int


_FIXED_RECEIPT_SOURCE: _FixedReceiptSource | None = None


@contextmanager
def _source_qualification(store, snapshot, transport_store, driver):
    executable = snapshot.program_execution_spec.invocation["executable_identity"]["absolute_path"]
    if executable in {"/opt/auto-g16-fixtures/bin/xtb", "/opt/auto-g16-fixtures/bin/crest"}:
        if driver is None or driver.runtime_qualification.get("bootstrap_protocol") != "synthetic-v31-program-effect/1":
            raise TransportBoundaryError("synthetic source requires explicit inert qualification")
        yield store, driver.runtime_qualification
        return
    fixed = _FIXED_RECEIPT_SOURCE
    if type(fixed) is not _FixedReceiptSource or fixed.snapshot_id != snapshot.program_execution_snapshot_id:
        raise TransportBoundaryError("fixed historical source locator NOT_ACQUIRED")
    if snapshot.program_execution_spec.program_kind != "xtb" or snapshot._completion_material()["schema"] != c._PILOT_MATERIAL_SCHEMA:
        raise TransportBoundaryError("historical source requires the exact original xTB tuple")
    from auto_g16.transport._bridge import _PROGRAM_BOOTSTRAP_SOURCE_BYTES
    if (sha256(_PROGRAM_BOOTSTRAP_SOURCE_BYTES).hexdigest(), len(_PROGRAM_BOOTSTRAP_SOURCE_BYTES)) != (fixed.bootstrap_source_sha256, fixed.bootstrap_source_size_bytes):
        raise TransportBoundaryError("historical bootstrap source changed")
    pins = []
    view = None
    def current():
        if _FIXED_RECEIPT_SOURCE is not fixed:
            raise TransportBoundaryError("historical source locator changed")
        for native, binding in ((store, fixed.core), (transport_store, fixed.transport)):
            if native._connection.in_transaction or native._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise TransportBoundaryError("historical source requires idle DELETE journal databases")
            rows = native._connection.execute("PRAGMA database_list").fetchall()
            if [(row[1], row[2]) for row in rows] != [("main", binding.path)]:
                raise TransportBoundaryError("historical source is not the fixed original database")
            for suffix in ("-wal", "-shm", "-journal"):
                if os.path.lexists(binding.path + suffix):
                    raise TransportBoundaryError("historical source has a journal sidecar")
        for pin in pins:
            pin._read_and_check()
            if pin.raw[:16] != b"SQLite format 3\x00" or pin.raw[18:20] != b"\x01\x01":
                raise TransportBoundaryError("historical source bytes require rollback journal format")
    try:
        for binding in (fixed.core, fixed.transport):
            pins.append(_PinnedPublisherFile(binding, 64 * 1024 * 1024))
        current()
        # Interpret the pinned original bytes, never the caller's potentially
        # stale same-path SQLite connection. No on-disk clone is authority.
        from auto_g16.core import store as core_storage
        view = core_storage.SQLiteRuntimeStore()
        view._connection.deserialize(pins[0].raw)
        view._connection.execute("PRAGMA query_only=ON")
        if (view._connection.execute("PRAGMA query_only").fetchone()[0] != 1
                or view._connection.execute("PRAGMA user_version").fetchone()[0] != core_storage.SCHEMA_VERSION
                or core_storage._schema_identity(view._connection) != core_storage._expected_schema_identity()):
            raise TransportBoundaryError("historical Core bytes have an unsupported schema")
        material = snapshot._completion_material()
        manifest = c._deployment_projection(c._unbase64(material["deployment_manifest_base64"], c._Q_CAP))
        yield view, {"deployment_id": manifest["deployment_id"], "bootstrap_protocol": manifest["bootstrap_protocol"],
               "bootstrap_source_sha256": fixed.bootstrap_source_sha256,
               "bootstrap_source_size_bytes": fixed.bootstrap_source_size_bytes}
    finally:
        try:
            if len(pins) == 2:
                current()
        finally:
            if view is not None:
                view.close()
            for pin in reversed(pins):
                pin.close()


__all__: tuple[str, ...] = ()
