#!/usr/bin/env python3
"""Finite R4 Controller composition. No installed pilot is currently available.

Deployment fixes the private bindings below after separate exact review. There
is no runtime configuration argument, environment override, approval factory,
claim implementation, restart loop, or direct Transport operation in this file.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import os
import stat
import sqlite3
from contextlib import ExitStack

from auto_g16 import approval, core, execution
from auto_g16.execution.program import ProgramExecutionSnapshot
from auto_g16.execution.program_runtime import _ProgramExecutionPort
from auto_g16.transport import _program_rtwin as rtwin
from auto_g16.transport import program as transport
from auto_g16.transport._canonical import strict_canonical_json, canonical_json_bytes


@dataclass(frozen=True, slots=True)
class _PilotStoreBinding:
    role: str
    store: object
    path: str
    parent_chain: tuple[tuple[int, int], ...]
    file_identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _FixedPilotRun:
    snapshot: ProgramExecutionSnapshot
    current_profile: execution.ServerProfile
    stores: tuple[_PilotStoreBinding, ...]
    scientific_approval_id: str
    batch_submit_approval_id: str
    operational_confirmation_id: str
    displayed_semantic_meaning: Mapping[str, object]
    prepared_input_bytes: bytes
    pbs_template_bytes: bytes
    reviewed_semantics: rtwin._PublisherFileBinding
    code_files: tuple[rtwin._PublisherFileBinding, ...]


_FIXED_PILOT_RUN: _FixedPilotRun | None = None
_PILOT_ATTACHMENT_KEYS = frozenset({
    "qualification_payload_sha256", "qualification_file_sha256", "qualification_size_bytes",
    "qualification_path", "qualification_parent_chain", "qualification_file_identity",
    "probe_evidence_manifest_sha256", "deployment_readback_evidence_sha256",
    "owner_q_acceptance_evidence_sha256", "pilot_live_gate_evidence_sha256", "pilot_window",
})


class _PinnedStorePath:
    """Existing no-follow store walk retained across collection; contents may append."""

    def __init__(self, binding):
        self.binding, self.fds = binding, []
        path = binding.path
        if type(path) is not str or not path.startswith("/") or any(p in {"", ".", ".."} for p in path[1:].split("/")):
            raise rtwin._publisher_failure("noncanonical store path")
        parts = path[1:].split("/")
        if len(binding.parent_chain) != len(parts) or not 1 <= len(parts) <= 128:
            raise rtwin._publisher_failure("store parent inventory mismatch")
        for node in (*binding.parent_chain, binding.file_identity):
            if type(node) is not tuple or len(node) != 2 or any(type(v) is not int for v in node) or node[0] < 0 or node[1] < 1:
                raise rtwin._publisher_failure("store physical identity invalid")
        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            self.fds.append(os.open("/", flags | os.O_DIRECTORY))
            for part in parts[:-1]:
                self.fds.append(os.open(part, flags | os.O_DIRECTORY, dir_fd=self.fds[-1]))
            self.fds.append(os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=self.fds[-1]))
            self.assert_current()
        except BaseException:
            self.close()
            raise

    def assert_current(self):
        # Reuse the publisher's full descriptor/name/type/ancestor comparison.
        rtwin._PinnedPublisherFile._check_names(self)

    def close(self):
        while self.fds:
            os.close(self.fds.pop())

    def __enter__(self):
        self.assert_current()
        return self

    def __exit__(self, *_args):
        self.close()


def _assert_connected_store(store, path):
    databases = store._connection.execute("PRAGMA database_list").fetchall()
    if [row[2] for row in databases if row[1] == "main"] != [path]:
        raise rtwin._publisher_failure("connected database differs from installed binding")


def _assert_store_bindings(run):
    """Controller binds existing live handles to the independently installed paths."""
    expected = (("core", core.SQLiteRuntimeStore), ("approval", approval.SQLiteApprovalStore), ("transport", transport._ProgramTransportStore))
    if type(run) is not _FixedPilotRun or len(run.stores) != 3:
        raise rtwin._publisher_failure("fixed three-store package missing")
    stores = {}
    for binding, (role, kind) in zip(run.stores, expected):
        if type(binding) is not _PilotStoreBinding or binding.role != role or type(binding.store) is not kind:
            raise rtwin._publisher_failure("three-store role/type mismatch")
        with _PinnedStorePath(binding):
            _assert_connected_store(binding.store, binding.path)
        stores[role] = binding.store
    if len({b.path for b in run.stores}) != 3 or len({b.file_identity for b in run.stores}) != 3:
        raise rtwin._publisher_failure("three stores are not distinct")
    stores["transport"]._attest()
    return stores


def _probe_index(payload):
    entries = [{"role": "scheduler-scope", "evidence": payload["execution_domain"]["scheduler_scope_evidence"]},
               {"role": "controller-probe", "case_id": "P08", "evidence": payload["controller_probe"]["evidence"]}]
    for host in payload["hosts"]:
        entries.append({"role": "host-identity", "host_key": host["host_key"], "evidence": host["identity_evidence"]})
        entries.extend({"role": "location", "host_key": host["host_key"], "location_role": loc["role"], "evidence": loc["evidence"]} for loc in host["locations"])
        entries.extend({"role": "host-probe", "host_key": host["host_key"], "case_id": probe["case_id"], "evidence": probe["evidence"]} for probe in host["probes"])
    return {"schema": "v31-publisher-probe-evidence-index/1", "entries": entries}


def _validate_pilot_qualification_evidence(run, deployment, confirmation):
    """Replay the installation's reviewed interpretation; do not authenticate people.

    The <=64 KiB semantic file has exactly schema/owner_exact_q/live_gate. Each
    role has exactly raw {sha256,size_bytes} and scope. Owner scope is Q's two
    hashes; Live Gate adds profile/snapshot/Attempt/window. Both original bytes
    and this interpretation are independently pinned at installation, outside Q,
    basis and Confirmation. Raw prose/JSON never supplies an approval decision.
    """
    deployment.assert_current()
    _validate_pilot_qualification_identity(run, deployment, confirmation)


def _validate_pilot_qualification_identity(run, deployment, confirmation):
    deployment.assert_identity()
    basis, payload = deployment.basis, deployment.qualification["payload"]
    attachment = confirmation.confirmer_evidence.get("publisher_pilot")
    if not isinstance(attachment, Mapping) or set(attachment) != _PILOT_ATTACHMENT_KEYS:
        raise rtwin._publisher_failure("missing/unknown pilot Confirmation attachment")
    expected = {key: basis[key] for key in _PILOT_ATTACHMENT_KEYS if key != "deployment_readback_evidence_sha256"}
    expected["deployment_readback_evidence_sha256"] = deployment.installation.basis.sha256
    if canonical_json_bytes(rtwin._plain(attachment)) != canonical_json_bytes(expected):
        raise rtwin._publisher_failure("Confirmation differs from fixed installation")
    pin = rtwin._PinnedPublisherFile(run.reviewed_semantics, 65536)
    try:
        semantics = strict_canonical_json(pin.raw, "reviewed publisher semantics")
        transport._exact_keys(semantics, {"schema", "owner_exact_q", "live_gate"}, "reviewed semantics")
        if semantics["schema"] != "v31-publisher-reviewed-scope/1":
            raise rtwin._publisher_failure("unknown reviewed scope projection")
        qscope = {key: basis[key] for key in ("qualification_payload_sha256", "qualification_file_sha256")}
        live_scope = {**qscope, **{key: basis[key] for key in ("resolved_server_profile_id", "program_execution_snapshot_id", "pilot_window")}, "attempt_id": run.snapshot.attempt_id}
        for role, scope, hash_key in (("owner_exact_q", qscope, "owner_q_acceptance_evidence_sha256"), ("live_gate", live_scope, "pilot_live_gate_evidence_sha256")):
            entry = semantics[role]
            transport._exact_keys(entry, {"raw", "scope"}, role)
            raw = deployment.evidence[basis[hash_key]]
            expected_raw = {"sha256": basis[hash_key], "size_bytes": len(raw)}
            if type(entry["raw"].get("size_bytes")) is not int or entry["raw"] != expected_raw or entry["scope"] != scope:
                raise rtwin._publisher_failure("reviewed original/scope mismatch")
        index_raw = deployment.evidence[basis["probe_evidence_manifest_sha256"]]
        if len(index_raw) > 1024*1024 or canonical_json_bytes(strict_canonical_json(index_raw, "probe evidence index")) != canonical_json_bytes(_probe_index(payload)):
            raise rtwin._publisher_failure("probe index does not exactly cover qualification")
        pin._read_and_check()
    finally:
        pin.close()


def _prepare_first_publisher_pilot_port(run, stores):
    driver = rtwin._RTWinProgramEffectDriver(snapshot=run.snapshot, current_profile=run.current_profile, program_transport_store=stores["transport"])
    return _ProgramExecutionPort(snapshot=run.snapshot, program_transport_store=stores["transport"], driver=driver)


def _load_current_authorities(run, deployment):
    if _FIXED_PILOT_RUN is not run:
        raise rtwin._publisher_failure("fixed run package changed")
    stores = _assert_store_bindings(run)
    snapshot = run.snapshot
    snapshot.assert_identity_closed()
    if execution.resolve_server_profile(run.current_profile) != snapshot.resolved_server_profile:
        raise rtwin._publisher_failure("current profile drift")
    scientific = stores["approval"].load_scientific_approval(run.scientific_approval_id)
    batch = stores["approval"].load_batch_submit_approval(run.batch_submit_approval_id)
    confirmation = stores["approval"].load_current_operational_confirmation(run.operational_confirmation_id, snapshot)
    confirmation.assert_current(stores["core"], snapshot)
    _validate_pilot_qualification_evidence(run, deployment, confirmation)
    return stores, scientific, batch, confirmation


def _load_validate_current(run, deployment):
    stores, scientific, batch, confirmation = _load_current_authorities(run, deployment)
    snapshot = run.snapshot
    approval.validate_effect_authority(
        runtime_store=stores["core"], attempt=stores["core"].load_attempt(snapshot.attempt_id),
        plan=stores["core"].load_calculation_plan(snapshot.calculation_plan_id),
        displayed_semantic_meaning=run.displayed_semantic_meaning,
        scientific_approval=scientific, batch_submit_approval=batch,
        execution_snapshot=snapshot, operational_confirmation=confirmation,
    )
    return stores, confirmation


@contextmanager
def _fixed_pilot_context():
    run = _FIXED_PILOT_RUN
    if type(run) is not _FixedPilotRun:
        raise rtwin._publisher_failure("fixed Controller package NOT_ACQUIRED")
    stores = _assert_store_bindings(run)
    snapshot = run.snapshot
    # Actual source paths, not caller-named replacement files, are pinned.
    from auto_g16.execution import _program_completion, _program_completion_wrapper, program, program_runtime
    actual = {str(Path(module.__file__).resolve()) for module in (_program_completion, _program_completion_wrapper, program, program_runtime, rtwin)} | {str(Path(__file__).resolve())}
    if {b.path for b in run.code_files} != actual or len(run.code_files) != len(actual):
        raise rtwin._publisher_failure("installed code inventory differs")
    code_pins = []
    deployment = None
    try:
        for binding in run.code_files:
            code_pins.append(rtwin._PinnedPublisherFile(binding, 4*1024*1024))
        authority = rtwin._driver._resolve_closed_profile_authority(snapshot.resolved_server_profile, run.current_profile, snapshot.program_execution_snapshot_id, successor=True)
        deployment = rtwin._read_fixed_publisher_deployment(authority, snapshot)
        yield run, stores, deployment, code_pins
    finally:
        if deployment is not None:
            deployment.close()
        for pin in reversed(code_pins):
            pin.close()


def _run_first_publisher_pilot():
    with _fixed_pilot_context() as (run, stores, deployment, code_pins):
        stores, confirmation = _load_validate_current(run, deployment)
        port = _prepare_first_publisher_pilot_port(run, stores)
        try:
            for pin in code_pins:
                pin._read_and_check()
            stores, confirmation = _load_validate_current(run, deployment)
            return execution.execute_once(
                stores["core"], snapshot=run.snapshot, current_profile=run.current_profile,
                prepared_input_bytes=run.prepared_input_bytes, pbs_template_bytes=run.pbs_template_bytes,
                confirmed_execution_snapshot_id=confirmation.execution_snapshot_id, port=port,
            )
        finally:
            if type(port.driver) is rtwin._RTWinProgramEffectDriver:
                port.driver.close()


def _collect_first_publisher_pilot():
    """One bounded collection under the same installed scope; never resubmit.

    Submitted-phase checks deliberately do not call the PLANNED-only validator.
    Reopening does not confer authority: the same current installed run, original
    scope, current approvals and window must all still match.
    """
    from auto_g16.execution.program_runtime import _collect_program_completion, _replay_program_completion
    with _fixed_pilot_context() as (run, stores, deployment, code_pins):
        stores, scientific, batch, confirmation = _load_current_authorities(run, deployment)
        snapshot = run.snapshot
        if stores["core"].attempt_state(snapshot.attempt_id) not in {core.AttemptState.SUBMITTED, core.AttemptState.RUNNING, core.AttemptState.SUCCEEDED, core.AttemptState.FAILED}:
            raise rtwin._publisher_failure("pilot collection is outside submitted scope")
        plan = stores["core"].load_calculation_plan(snapshot.calculation_plan_id)
        attempt = stores["core"].load_attempt(snapshot.attempt_id)
        scientific.assert_current(plan, displayed_semantic_meaning=run.displayed_semantic_meaning)
        expected = approval.BatchApprovalMember(attempt_id=attempt.attempt_id, task_id=attempt.task_id, calculation_plan_id=plan.calculation_plan_id, calculation_plan_revision=plan.revision, scientific_approval_id=scientific.scientific_approval_id)
        if batch.member_for(attempt.attempt_id) != expected:
            raise rtwin._publisher_failure("pilot collection Batch scope differs")
        port = _prepare_first_publisher_pilot_port(run, stores)
        try:
            for pin in code_pins:
                pin._read_and_check()
            # Re-read mutable approval storage after preparing the mechanical port.
            current = _load_current_authorities(run, deployment)
            if current[1:] != (scientific, batch, confirmation):
                raise rtwin._publisher_failure("pilot collection approvals changed")
            if stores["core"].attempt_state(snapshot.attempt_id) in {core.AttemptState.SUCCEEDED, core.AttemptState.FAILED}:
                return _replay_program_completion(stores["core"], snapshot=snapshot, program_transport_store=stores["transport"], driver=port.driver)
            return _collect_program_completion(stores["core"], snapshot=snapshot, program_transport_store=stores["transport"], driver=port.driver, input_bytes={snapshot.program_execution_spec.exact_inputs[0]["portable_name"]: run.prepared_input_bytes})
        finally:
            if type(port.driver) is rtwin._RTWinProgramEffectDriver:
                port.driver.close()


@dataclass(frozen=True, slots=True)
class _CollectionDatabaseBinding:
    role: str
    path: str
    parent_chain: tuple[tuple[int, int], ...]
    file_identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _FixedCollectionRun:
    current_profile: execution.ServerProfile
    databases: tuple[_CollectionDatabaseBinding, ...]
    store_root: str
    snapshot_semantics: rtwin._PublisherFileBinding
    prepared_input: rtwin._PublisherFileBinding
    pbs_script: rtwin._PublisherFileBinding
    reviewed_pilot_semantics: rtwin._PublisherFileBinding
    displayed_semantic_meaning: Mapping[str, object]


_FIXED_COLLECTION_RUN: _FixedCollectionRun | None = None


def _open_collection_stores(run, stack):
    """Pin all existing paths before any create-capable SQLite constructor."""
    from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal
    roles = ("core", "approval", "transport", "project-journal")
    if type(run.databases) is not tuple or len(run.databases) != 4:
        raise rtwin._publisher_failure("fixed four-store package missing")
    pins = []
    for binding, role, version in zip(run.databases, roles, (1, 1, 2, 2)):
        if type(binding) is not _CollectionDatabaseBinding or binding.role != role:
            raise rtwin._publisher_failure("fixed four-store roles differ")
        pins.append(stack.enter_context(_PinnedStorePath(binding)))
        # Read-only URI cannot manufacture an empty file before version checks.
        connection = sqlite3.connect(Path(binding.path).as_uri() + "?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != version:
                raise rtwin._publisher_failure("existing collection schema differs")
        finally:
            connection.close()
        pins[-1].assert_current()
    if len({b.path for b in run.databases}) != 4 or len({b.file_identity for b in run.databases}) != 4:
        raise rtwin._publisher_failure("fixed four stores are not distinct")
    stores = {}
    for binding in run.databases:
        if binding.role == "core":
            handle = core.SQLiteRuntimeStore(binding.path)
        elif binding.role == "approval":
            handle = approval.SQLiteApprovalStore(binding.path)
        elif binding.role == "transport":
            handle = transport._ProgramTransportStore.open_existing(binding.path, approved_root=run.store_root)
        else:
            handle = _ProductionProvisioningJournal.open_existing(Path(binding.path), approved_root=Path(run.store_root))
        stack.callback(handle.close)
        stores[binding.role] = handle
        for pin in pins:
            pin.assert_current()
        _assert_connected_store(handle, binding.path)
    return stores, pins


def _collection_store_identity(run, stores, base):
    values = []
    for binding in run.databases:
        value = {"role": binding.role, "path": binding.path,
                 "parent_chain": [{"device": d, "inode": i} for d, i in binding.parent_chain],
                 "file_identity": {"device": binding.file_identity[0], "inode": binding.file_identity[1]}}
        if binding.role == "transport":
            value.update({k: base[k] for k in ("program_transport_store_id", "store_instance_id", "runtime_attestation_id")})
        elif binding.role == "project-journal":
            value["journal_identity"] = stores["project-journal"]._identity
        values.append(value)
    return values


def _validate_collection_review(deployment):
    from auto_g16.execution._identity import semantic_sha256, freeze_mapping
    binding = deployment.installation.reviewed_scope
    pin = rtwin._PinnedPublisherFile(binding, 65536)
    try:
        scope = {k: v for k, v in deployment.document.items() if k != "review_evidence"}
        scope_hash = semantic_sha256(freeze_mapping(scope, "collection review scope"))
        expected = {"schema": "v31-collection-reviewed-scope/1"}
        for role in ("owner_continuation", "source_compatibility"):
            expected[role] = {"raw": deployment.document["review_evidence"][role], "scope_sha256": scope_hash}
        observed = strict_canonical_json(pin.raw, "reviewed collection scope")
        if canonical_json_bytes(observed) != canonical_json_bytes(expected):
            raise rtwin._publisher_failure("collection decision/scope differs")
        pin._read_and_check()
    finally:
        pin.close()


def _collection_original_approvals(run, stores, deployment):
    original = deployment.document["original"]
    snapshot = deployment.snapshot
    scientific = stores["approval"].load_scientific_approval(original["scientific_approval_id"])
    batch = stores["approval"].load_batch_submit_approval(original["batch_submit_approval_id"])
    confirmation = stores["approval"].load_current_operational_confirmation(original["operational_confirmation_id"], snapshot)
    confirmation.assert_current(stores["core"], snapshot)
    plan = stores["core"].load_calculation_plan(snapshot.calculation_plan_id)
    attempt = stores["core"].load_attempt(snapshot.attempt_id)
    scientific.assert_current(plan, displayed_semantic_meaning=run.displayed_semantic_meaning)
    expected = approval.BatchApprovalMember(attempt_id=attempt.attempt_id, task_id=attempt.task_id,
                                            calculation_plan_id=plan.calculation_plan_id,
                                            calculation_plan_revision=plan.revision,
                                            scientific_approval_id=scientific.scientific_approval_id)
    if batch.decision is not approval.ApprovalDecision.APPROVED or batch.member_for(attempt.attempt_id) != expected:
        raise rtwin._publisher_failure("collection original Batch scope differs")
    # Identity-only validation of the original scope never extends its window.
    from types import SimpleNamespace
    _validate_pilot_qualification_identity(SimpleNamespace(snapshot=snapshot, reviewed_semantics=run.reviewed_pilot_semantics), deployment.original, confirmation)
    return scientific, batch, confirmation


def _resume_fixed_publisher_collection():
    """One explicitly installed continuation. No CLI, default-submit or retry path."""
    from auto_g16.execution import program, program_runtime
    from auto_g16.execution.project_provisioning import _ProjectProvisioningService
    run = _FIXED_COLLECTION_RUN
    if type(run) is not _FixedCollectionRun:
        raise rtwin._publisher_failure("fixed collection run NOT_ACQUIRED")
    with ExitStack() as stack:
        assets = {}
        for role, binding, cap in (("snapshot", run.snapshot_semantics, 8*1024*1024),
                                   ("input", run.prepared_input, 16*1024*1024),
                                   ("pbs", run.pbs_script, 8*1024*1024)):
            pin = rtwin._PinnedPublisherFile(binding, cap)
            stack.callback(pin.close)
            assets[role] = pin
        stores, pins = _open_collection_stores(run, stack)
        with stores["transport"]._completion_guard() as token:
            resolved = execution.resolve_server_profile(run.current_profile)
            attestor = rtwin._RTWinProjectAttestor(current_profile=run.current_profile, target=resolved)
            service = _ProjectProvisioningService._from_project_attestor(attestor=attestor, target=resolved, journal=stores["project-journal"])
            snapshot = program._ProgramExecutionSnapshotService._for_production(project_provisioning=service, target=resolved).restore_for_collection(
                stores["core"], reviewed_semantics=strict_canonical_json(assets["snapshot"].raw, "original expanded snapshot"))
            if resolved != snapshot.resolved_server_profile or assets["pbs"].raw != snapshot.scheduler_artifacts[0]["content_utf8"].encode():
                raise rtwin._publisher_failure("restored profile/PBS differs")
            driver = rtwin._RTWinProgramEffectDriver._for_fixed_collection(snapshot=snapshot, current_profile=run.current_profile, program_transport_store=stores["transport"])
            stack.callback(driver.close)
            deployment = driver._publisher
            _validate_collection_review(deployment)
            initial_approvals = _collection_original_approvals(run, stores, deployment)
            if canonical_json_bytes(rtwin._plain(initial_approvals[2].execution_snapshot_semantics)) != assets["snapshot"].raw:
                raise rtwin._publisher_failure("persisted original review differs from installed snapshot")
            base = program_runtime._snapshot_binding(snapshot, stores["transport"], driver)
            if canonical_json_bytes(_collection_store_identity(run, stores, base)) != canonical_json_bytes(deployment.document["stores"]):
                raise rtwin._publisher_failure("collection original store identities differ")

            def checkpoint():
                if _FIXED_COLLECTION_RUN is not run:
                    raise rtwin._publisher_failure("fixed collection run changed")
                for pin in pins:
                    pin.assert_current()
                for pin in assets.values():
                    pin._read_and_check()
                for binding in run.databases:
                    _assert_connected_store(stores[binding.role], binding.path)
                stores["transport"]._attest()
                program._assert_collection_local_workspace(snapshot)
                if stores["project-journal"].load_binding(snapshot.project_physical_binding.project_id) != snapshot.project_physical_binding:
                    raise rtwin._publisher_failure("collection Project journal changed")
                driver._authority()
                _validate_collection_review(deployment)
                if _collection_original_approvals(run, stores, deployment) != initial_approvals:
                    raise rtwin._publisher_failure("collection original approvals changed")

            return program_runtime._resume_program_collection(
                stores["core"], snapshot=snapshot, program_transport_store=stores["transport"], driver=driver,
                input_bytes={snapshot.program_execution_spec.exact_inputs[0]["portable_name"]: assets["input"].raw},
                continuation=deployment.document, continuation_sha256=deployment.installation.continuation.sha256,
                checkpoint=checkpoint, _completion_token=token)


if __name__ == "__main__":
    _run_first_publisher_pilot()
