"""Fixed local source locator for historical proof; never a live installation."""
from contextlib import contextmanager
from contextvars import ContextVar
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
    project_association: object = None


_FIXED_RECEIPT_SOURCE: _FixedReceiptSource | None = None
_FIXED_CREST_RECEIPT_SOURCE: _FixedReceiptSource | None = None
_FIXED_GAUSSIAN_RECEIPT_SOURCE: _FixedReceiptSource | None = None
_GAUSSIAN_SOURCES = ContextVar("gaussian_historical_sources", default=None)


@contextmanager
def _gaussian_receipt_sources(sources):
    """Explicit request-local originals; never a live or inferred registration."""
    if (type(sources) is not tuple or not sources
            or any(type(item) is not _FixedReceiptSource for item in sources)
            or len({item.snapshot_id for item in sources}) != len(sources)):
        raise TransportBoundaryError("invalid Gaussian historical source catalogue")
    if _GAUSSIAN_SOURCES.get() is not None:
        raise TransportBoundaryError("Gaussian historical source catalogue already active")
    token = _GAUSSIAN_SOURCES.set(sources)
    try:
        yield
        if _GAUSSIAN_SOURCES.get() is not sources:
            raise TransportBoundaryError("Gaussian historical source catalogue changed")
    finally:
        _GAUSSIAN_SOURCES.reset(token)


@contextmanager
def _source_qualification(store, snapshot, transport_store, driver):
    from ._project_association import associated
    if associated(snapshot.project_physical_binding):
        from ._project_association_source import replay
        catalogue = _GAUSSIAN_SOURCES.get()
        fixed = next((item for item in catalogue if item.snapshot_id == snapshot.program_execution_snapshot_id), None) if catalogue else _FIXED_GAUSSIAN_RECEIPT_SOURCE
        if type(fixed) is not _FixedReceiptSource or fixed.snapshot_id != snapshot.program_execution_snapshot_id or fixed.project_association is None:
            raise TransportBoundaryError("registered historical association source NOT_ACQUIRED")
        with replay(snapshot.project_physical_binding, fixed.project_association):
            with _source_qualification_original(store, snapshot, transport_store, driver) as value:
                yield value
    else:
        with _source_qualification_original(store, snapshot, transport_store, driver) as value:
            yield value


@contextmanager
def _source_qualification_original(store, snapshot, transport_store, driver):
    executable = snapshot.program_execution_spec.invocation["executable_identity"]["absolute_path"]
    if executable in {"/opt/auto-g16-fixtures/bin/xtb", "/opt/auto-g16-fixtures/bin/crest", "/opt/auto-g16-fixtures/bin/g16"}:
        if driver is None or driver.runtime_qualification.get("bootstrap_protocol") != "synthetic-v31-program-effect/1":
            raise TransportBoundaryError("synthetic source requires explicit inert qualification")
        yield store, driver.runtime_qualification
        return
    from . import _crest_completion, _crest_startup
    kind = snapshot.program_execution_spec.program_kind
    def selected_source():
        catalogue = _GAUSSIAN_SOURCES.get()
        if kind == "gaussian" and catalogue is not None:
            return next((item for item in catalogue
                         if item.snapshot_id == snapshot.program_execution_snapshot_id), None)
        return {"crest": _FIXED_CREST_RECEIPT_SOURCE, "xtb": _FIXED_RECEIPT_SOURCE,
                "gaussian": _FIXED_GAUSSIAN_RECEIPT_SOURCE}.get(kind)
    fixed = selected_source()
    if type(fixed) is not _FixedReceiptSource or fixed.snapshot_id != snapshot.program_execution_snapshot_id:
        raise TransportBoundaryError("fixed historical source locator NOT_ACQUIRED")
    supported = {
        ("xtb", "auto-g16-v31-xtb", 3, c._PILOT_MATERIAL_SCHEMA),
        ("crest", "auto-g16-v31-crest", 3, _crest_completion._MATERIAL_SCHEMA),
        ("crest", "auto-g16-v31-crest", 3, _crest_startup._MATERIAL_SCHEMA),
    }
    supported.update(("gaussian", "auto-g16-v31-gaussian", version,
                      f"v31-completion-rendering-material/{version + 2}")
                     for version in (3, 4, 5, 6, 7))
    spec = snapshot.program_execution_spec
    if (kind, spec.adapter_id, spec.adapter_contract_version,
            snapshot._completion_material()["schema"]) not in supported:
        raise TransportBoundaryError("historical source requires the exact original receipt tuple")
    from auto_g16.transport._bridge import _PROGRAM_BOOTSTRAP_SOURCE_BYTES, _PRE_STARTUP_PROGRAM_BOOTSTRAP_SOURCE_BYTES
    known = {(sha256(raw).hexdigest(), len(raw)) for raw in (_PRE_STARTUP_PROGRAM_BOOTSTRAP_SOURCE_BYTES, _PROGRAM_BOOTSTRAP_SOURCE_BYTES)}
    if kind == "gaussian" and spec.adapter_contract_version in (4, 5, 6, 7):
        from auto_g16.transport import _gaussian_submit, _gaussian_file_submit, _gaussian_resource_submit
        if spec.adapter_contract_version == 7:
            from auto_g16.transport import _gaussian_freq_submit
            owner = _gaussian_freq_submit
        else:
            owner = {4: _gaussian_submit, 5: _gaussian_file_submit, 6: _gaussian_resource_submit}[spec.adapter_contract_version]
        raw = owner.source_bytes()
        known = {(sha256(raw).hexdigest(), len(raw))}

    if (fixed.bootstrap_source_sha256, fixed.bootstrap_source_size_bytes) not in known:
        raise TransportBoundaryError("historical bootstrap source changed")
    pins = []
    view = None
    def current():
        if selected_source() is not fixed:
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
