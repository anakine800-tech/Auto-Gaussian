"""Single closed production entry shared by normal and recovery Direct routes."""

from auto_g16.transport._canonical import TransportBoundaryError
from .installation import require_qualified_installation


def run_direct(scope, invocation):
    """No client data or synthetic object can qualify real process creation.

    The disabled seam is deliberate. Exact installation authentication, the
    original owner guard and target native qualification must be bound in a
    later reviewed activation gate; none can be fabricated from this worktree.
    """
    try:
        require_qualified_installation()
    except ValueError as exc:
        raise TransportBoundaryError("managed Direct production closed: native unqualified") from exc
    # No fallthrough, Popen fallback, automatic qualification or alternate UID.
    raise TransportBoundaryError("managed Direct activation unavailable")


# Private composition only. No endpoint, loader, setter or client activation.
from contextvars import ContextVar
from dataclasses import dataclass
from threading import get_ident

from auto_g16 import core, execution
from auto_g16._managed_offline.common import Rejected, decode_frame, frame
from auto_g16._managed_offline.intake import Intake
from auto_g16._managed_offline.review import Review
from auto_g16.transport import program as transport
from .installation import Installation
from .lifecycle import Lifecycle
from .supervisor import Supervisor
from . import ipc

_ACTIVE = ContextVar("managed_direct_owner", default=None)
_DRIVER = ContextVar("managed_direct_driver", default=None)
_PROTOCOL = "auto-g16-managed-direct-ipc/1"


@dataclass(frozen=True)
class _Call:
    composition: object
    slot: object
    snapshot: object
    ids: tuple
    peer_uid: int


def _require_managed_driver(driver):
    from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
    call = _ACTIVE.get()
    if type(call) is not _Call or type(driver) is not _RTWinProgramEffectDriver:
        raise TransportBoundaryError("managed Direct owner missing")
    owner = call.composition
    owner._check()
    if (owner.life.owner != get_ident() or owner.life.state != "OPEN"
            or driver._snapshot is not call.snapshot or driver._profile is not owner.profile
            or driver._store is not owner.transport or driver._collection_only or driver._recovery_only):
        raise TransportBoundaryError("managed Direct owner differs")
    return call


def _run_owned(scope, invocation):
    """Shared lower composition, tested inertly; production entry remains closed.

    The only concrete native adapter still refuses loading independently. Tests
    replace that adapter and call this private seam; they cannot qualify it.
    """
    from auto_g16.transport import _bridge, _driver, _program_rtwin as bridge
    from .darwin import DarwinOwner
    driver = _DRIVER.get()
    # Burn the current handoff before any admission rejection can be caught
    # and retried within the same original driver invocation.
    handoff = bridge._consume_direct_wire(driver, scope, invocation)
    call = _require_managed_driver(driver)
    owner = call.composition
    if (type(invocation) is not bridge._ProgramRTWinInvocation or scope is not call.snapshot
            or type(invocation.authority.ssh_effect) is not _driver._MacDirectEffectAuthority):
        raise TransportBoundaryError("managed Direct invocation differs")

    def recheck():
        handoff.assert_consumed(driver, scope, invocation)
        _require_managed_driver(driver)
        owner.transport._require_current_completion_owner()
        owner.review.recheck_launch_scope(call.slot.key[2], ids=call.ids, peer_uid=call.peer_uid)
        if invocation.authority != driver._authority():
            raise TransportBoundaryError("managed Direct authority drift")
        return bridge._prepare_program_invocation(scope, invocation)

    # Check before even constructing a native adapter, then again while M is held.
    _command, request = recheck()
    adapter = DarwinOwner(owner.installation, scope, invocation.authority, _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES)
    supervisor = Supervisor(adapter, owner.life.poison)
    try:
        def before_start():
            if recheck() != (_command, request):
                raise TransportBoundaryError("managed Direct wire changed")
        owner.life.launch(supervisor, request, invocation.operation, before_start)
        return supervisor.finish()
    except BaseException:
        supervisor.retain_unknown()
        raise


class _Composition:
    """Trusted in-process objects, never serialized or supplied by an IPC client."""
    def __init__(self, *, installation, life, review, profile, program_transport_store):
        self.installation, self.life, self.review = installation, life, review
        self.profile, self.transport = profile, program_transport_store
        self._binding = (installation, life, review, profile, program_transport_store)
        self._check()
        self.admissions = {role: ipc.Admission(role) for role in ("consumer", "material", "review", "lifecycle")}

    def _check(self):
        if (type(self.installation) is not Installation or type(self.life) is not Lifecycle
                or type(self.review) is not Review or type(self.review.intake) is not Intake
                or type(self.profile) is not execution.ServerProfile
                or type(self.transport) is not transport._ProgramTransportStore
                or any(a is not b for a, b in zip(self._binding, (self.installation, self.life, self.review, self.profile, self.transport)))
                or self.life.installation is not self.installation or self.review.life is not self.life
                or self.review.intake._root.lifecycle is not self.life
                or self.review.installation_hash != self.installation.description_sha256
                or self.review.uid != self.installation.desktop_uid
                or self.review.intake.requester_uid != self.installation.desktop_uid
                or self.review.scope["requester_uids"] != [self.installation.desktop_uid]
                or type(self.review.intake.store) is not core.SQLiteRuntimeStore
                or execution.resolve_server_profile(self.profile) != self.review.intake.profile):
            raise Rejected("SCOPE")
        self.life._integrity()
        self.review.intake.root()

    def handle(self, role, connection):
        self._check()
        if role not in self.admissions:
            raise Rejected("SCOPE")
        uid = 0 if role == "lifecycle" else self.installation.desktop_uid
        return self.admissions[role].handle(connection, uid=uid,
            handler=lambda value, peer: self._dispatch(role, value, peer))

    def _dispatch(self, role, value, peer_uid):
        self._check()
        if role == "material":
            return decode_frame(self.review.intake.request(frame(value, 65536), peer_uid=peer_uid), 65536, eof=True)
        if role == "review":
            return decode_frame(self.review.request(frame(value, 16384), peer_uid=peer_uid), 262144, eof=True)
        if role == "lifecycle":
            operation = ipc.lifecycle_request(value)
            before = self.life.state
            try:
                state = self.life.manage(operation, peer_uid=peer_uid)
                disposition = "READ_ONLY" if operation == "STATUS" or operation == "STOP" and before in ("STOPPED", "BLOCKED") else "APPLIED"
            except Rejected as exc:
                state, disposition = self.life.state, "BUSY" if exc.reason == "BUSY" else "REJECTED"
            return {"protocol": "auto-g16-managed-lifecycle/1", "operation": operation,
                    "disposition": disposition, "lifecycle": state,
                    "active_composition": self.life.c.locked(), "known_child_count": len(self.life.children)}
        if role != "consumer":
            raise Rejected("SCOPE")
        return self._consumer(value, peer_uid)

    def _local(self, slot):
        # One read of the original Core rows. No RPC cache, marker inference or
        # recreated intent. C prevents another managed composition writing here.
        store = self.review.intake.store
        row = store._db().execute("SELECT state, EXISTS(SELECT 1 FROM submission_intents WHERE attempt_id=attempts.attempt_id) FROM attempts WHERE attempt_id=?", (slot.records[3].attempt_id,)).fetchone()
        if row is None:
            raise Rejected("STORE_UNAVAILABLE")
        state = core.AttemptState(row[0]).value
        from auto_g16.transport._submission_recovery import START
        reconciliation = any(o.observation_type == START for o in store.observations_for_attempt(slot.records[3].attempt_id))
        return {"core_state": state, "submission_consumed": bool(row[1]),
                "reconciliation_consumed": reconciliation, "collection_consumed": None}

    def _consumer(self, value, peer_uid):
        response = dict(protocol=_PROTOCOL, operation=None, attempt_id=None, disposition="REJECTED",
            core_state=None, submission_consumed=None, reconciliation_consumed=None, collection_consumed=None,
            reason="INVALID_REQUEST")
        try:
            operation = ipc.consumer_request(value)
            if type(peer_uid) is not int or peer_uid != self.installation.desktop_uid:
                response["reason"] = "ACCESS_DENIED"
                return response
            with self.life.composition(readonly=operation == "QUERY_LOCAL_STATUS"):
                self._check()
                slots = [s for s in self.review.intake.root()._allocated if s.records[3].attempt_id == value["scope"]["attempt_id"]]
                if len(slots) != 1:
                    raise Rejected("SCOPE")
                slot = slots[0]
                if operation == "QUERY_LOCAL_STATUS":
                    response.update(self._local(slot), operation=operation, attempt_id=slot.records[3].attempt_id,
                                    disposition="LOCAL_STATE", reason="OK")
                    return response
                scope = value["scope"]
                if slot.snapshot is None or slot.snapshot.program_execution_snapshot_id != scope["snapshot_id"]:
                    raise Rejected("SCOPE")
                if self.review.intake.store.attempt_state(slot.records[3].attempt_id) is not core.AttemptState.PLANNED:
                    response["reason"] = "STATE_NOT_ELIGIBLE"
                    return response
                ids = tuple(scope[k] for k in ("scientific_approval_id", "batch_submit_approval_id", "operational_confirmation_id"))
                snapshot = self.review.validate_execution(slot.key[2], ids=ids, peer_uid=peer_uid)
                self._execute(_Call(self, slot, snapshot, ids, peer_uid))
                response.update(self._local(slot), operation=operation, attempt_id=slot.records[3].attempt_id)
                if response["core_state"] in ("UNKNOWN", "SUBMISSION_INTENT_RECORDED"):
                    response.update(disposition="UNRESOLVED", reason="OPERATION_UNRESOLVED")
                else:
                    response.update(disposition="COMPLETED", reason="OK")
        except Rejected as exc:
            response.update(disposition="BUSY" if exc.reason == "BUSY" else "REJECTED",
                reason={"BUSY": "OWNER_BUSY", "LIFECYCLE_BLOCKED": "ADMISSION_CLOSED", "BAD_FRAME": "INVALID_REQUEST"}.get(exc.reason, "AUTHORITY_NOT_CURRENT"))
        except Exception:
            self.life.poison()
            response.update(disposition="UNRESOLVED", reason="STATE_UNAVAILABLE")
        return response

    def _execute(self, call):
        from auto_g16.execution.program_runtime import _ProgramExecutionPort
        from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
        if _ACTIVE.get() is not None or _DRIVER.get() is not None:
            raise Rejected("BUSY")
        token = _ACTIVE.set(call)
        driver = None
        try:
            driver = _RTWinProgramEffectDriver(snapshot=call.snapshot, current_profile=self.profile,
                                              program_transport_store=self.transport)
            owned = _DRIVER.set(driver)
            try:
                return execution.execute_once(self.review.intake.store, snapshot=call.snapshot,
                    current_profile=self.profile, prepared_input_bytes=call.slot.material.xyz,
                    pbs_template_bytes=call.snapshot.scheduler_artifacts[0]["content_utf8"].encode(),
                    confirmed_execution_snapshot_id=call.snapshot.program_execution_snapshot_id,
                    port=_ProgramExecutionPort(snapshot=call.snapshot, program_transport_store=self.transport, driver=driver))
            finally:
                _DRIVER.reset(owned)
        finally:
            if driver is not None:
                driver.close()
            _ACTIVE.reset(token)
