"""RTwin-first v3 execution and read adapters over fixed typed operations."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re
from threading import Lock
from typing import Callable, Final

from auto_g16.execution import (
    ConfirmedNoEffectError,
    EffectKind,
    EffectState,
    ExecutionSnapshot,
    PossiblyEffectfulError,
    RemoteEffectReceipt,
    ServerProfile,
    assert_execution_snapshot_identity,
)

from ._canonical import TransportBoundaryError, canonical_bytes
from ._driver import (
    _FetchResult,
    _Invocation,
    _OPERATION_TABLE_BYTES,
    _RTWinDriver,
    _SubprocessRTWinDriver,
    _TextResult,
    _is_fetch_result_closed,
    _is_text_result_closed,
    _operation,
)
from .models import (
    MAX_FETCH_ARTIFACT_BYTES,
    MAX_FETCH_CAPTURE_BYTES,
    ExactArtifactRequest,
    ExactRemoteJobBinding,
    FetchedArtifact,
    FetchedOutputCapture,
    SchedulerReadEvidence,
    _assert_binding_matches_snapshot,
    _validate_requests,
)


_JOB_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_QSTAT_FIELD: Final = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_.-]*) = (.+)$")
_WINDOWS_ABSOLUTE: Final = re.compile(r"^[A-Z]:\\")
_REQUIRED_PATHS: Final = (
    "rtwin_root",
    "known_hosts",
    "mac_ssh_executable",
    "mac_scp_executable",
    "rtwin_ssh_executable",
    "rtwin_scp_executable",
    "rtwin_bridge_executable",
    "server_python_executable",
    "server_qsub_executable",
    "server_qstat_executable",
)
_REQUIRED_RUNTIME: Final = (
    "auto-g16-rtwin-operation-table/1",
    "rtwin-pbs-v1",
    "mac-ssh",
    "mac-scp",
    "rtwin-ssh",
    "rtwin-scp",
    "rtwin-bridge",
    "server-python",
    "server-qsub",
    "server-qstat",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _runtime_identity(value: object, name: str) -> tuple[str, int]:
    if not hasattr(value, "keys") or set(value) != {"sha256", "size_bytes"}:  # type: ignore[arg-type]
        raise TransportBoundaryError(f"runtime identity {name} has invalid shape")
    digest = value["sha256"]  # type: ignore[index]
    size = value["size_bytes"]  # type: ignore[index]
    if not isinstance(digest, str) or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise TransportBoundaryError(f"runtime identity {name} has invalid digest")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise TransportBoundaryError(f"runtime identity {name} has invalid size")
    return digest, size


def _attest_runtime(snapshot: ExecutionSnapshot) -> None:
    try:
        assert_execution_snapshot_identity(snapshot)
    except Exception as exc:
        raise TransportBoundaryError("ExecutionSnapshot identity is not closed") from exc
    if snapshot.adapter_contract_version != "rtwin-pbs-v1":
        raise TransportBoundaryError("snapshot does not select the RTwin adapter contract")
    profile = snapshot.resolved_server_profile
    if profile.transport_kind != "legacy_rtwin_pbs":
        raise TransportBoundaryError("snapshot does not select the RTwin/PBS route")
    if snapshot.workspace_binding.rtwin_attempt_dir is None:
        raise TransportBoundaryError("RTwin adapter requires an exact RTwin Attempt workspace")
    paths = profile.platform_paths
    for key in _REQUIRED_PATHS:
        value = paths.get(key)
        if not isinstance(value, str) or not value:
            raise TransportBoundaryError(f"snapshot lacks Transport platform path {key}")
        if not value.startswith("/") and _WINDOWS_ABSOLUTE.match(value) is None:
            raise TransportBoundaryError(f"Transport platform path {key} is not absolute")
    identities = profile.runtime_identities
    for name in _REQUIRED_RUNTIME:
        if name not in identities:
            raise TransportBoundaryError(f"snapshot lacks runtime identity {name}")
        _runtime_identity(identities[name], name)
    table_digest, table_size = _runtime_identity(
        identities["auto-g16-rtwin-operation-table/1"],
        "auto-g16-rtwin-operation-table/1",
    )
    if table_digest != sha256(_OPERATION_TABLE_BYTES).hexdigest() or table_size != len(
        _OPERATION_TABLE_BYTES
    ):
        raise TransportBoundaryError("snapshot RTwin operation table identity drifted")


def _text_success(result: _TextResult) -> bool:
    return (
        isinstance(result, _TextResult)
        and result.completion_status == "completed"
        and result.returncode == 0
        and result.stdout == b""
        and result.stderr == b""
        and result.eof_stdout
        and result.eof_stderr
    )


def _invoke_text(
    driver: _RTWinDriver, snapshot: ExecutionSnapshot, invocation: _Invocation
) -> _TextResult:
    try:
        result = driver.invoke_text(snapshot, invocation)
    except TransportBoundaryError as exc:
        raise ConfirmedNoEffectError(
            _effect_kind(invocation.operation.name),
            f"rtwin-{invocation.operation.name}-preflight-failed",
        ) from exc
    except Exception as exc:
        raise PossiblyEffectfulError(
            _effect_kind(invocation.operation.name),
            f"rtwin-{invocation.operation.name}-driver-error",
        ) from exc
    if not _is_text_result_closed(result):
        raise PossiblyEffectfulError(
            _effect_kind(invocation.operation.name),
            f"rtwin-{invocation.operation.name}-malformed-result",
        )
    return result


def _effect_kind(operation_name: str) -> EffectKind:
    return {
        "allocate": EffectKind.REMOTE_WORKSPACE,
        "stage": EffectKind.INPUT_TRANSFER,
        "qsub": EffectKind.SUBMISSION,
        "qstat": EffectKind.SUBMISSION_RECONCILIATION,
    }.get(operation_name, EffectKind.SUBMISSION_RECONCILIATION)


def _qstat_classification(
    binding: ExactRemoteJobBinding, result: _TextResult
) -> tuple[str, str, str, int]:
    if not _is_text_result_closed(result):
        result = _TextResult(
            stdout=b"",
            stderr=b"",
            returncode=None,
            eof_stdout=False,
            eof_stderr=False,
            completion_status="transport-error",
        )
    if len(result.stdout) > 262_144 or len(result.stderr) > 65_536:
        stdout = b""
        stderr = b""
        result = _TextResult(
            stdout=stdout,
            stderr=stderr,
            returncode=None,
            eof_stdout=False,
            eof_stderr=False,
            completion_status="transport-error",
        )
    acquisition = [
        result.stdout,
        result.stderr,
        result.returncode,
        result.eof_stdout,
        result.eof_stderr,
        result.completion_status,
    ]
    evidence_sha256 = sha256(canonical_bytes(acquisition)).hexdigest()
    evidence_size = len(result.stdout) + len(result.stderr)
    if (
        result.completion_status != "completed"
        or not result.eof_stdout
        or not result.eof_stderr
    ):
        return "unknown", "unknown", evidence_sha256, evidence_size
    if (
        result.returncode == 153
        and result.stdout == b""
        and result.stderr == f"qstat: Unknown Job Id {binding.job_id}\n".encode("ascii")
    ):
        return "absent", "fresh", evidence_sha256, evidence_size
    if result.returncode != 0 or result.stderr:
        return "unknown", "unknown", evidence_sha256, evidence_size
    if b"\x00" in result.stdout or b"\r" in result.stdout:
        return "unknown", "unknown", evidence_sha256, evidence_size
    try:
        text = result.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "unknown", "unknown", evidence_sha256, evidence_size
    if not text.endswith("\n") or text.endswith("\n\n"):
        return "unknown", "unknown", evidence_sha256, evidence_size
    lines = text[:-1].split("\n")
    if not lines or lines[0] != f"Job Id: {binding.job_id}" or len(lines) < 2:
        return "unknown", "unknown", evidence_sha256, evidence_size
    fields: dict[str, str] = {}
    for line in lines[1:]:
        match = _QSTAT_FIELD.fullmatch(line)
        if match is None:
            return "unknown", "unknown", evidence_sha256, evidence_size
        name, value = match.groups()
        if name in fields or not value or value != value.strip():
            return "unknown", "unknown", evidence_sha256, evidence_size
        fields[name] = value
    state = fields.get("job_state")
    if state is None or len(state) != 1 or not state.isascii() or not state.isupper():
        return "unknown", "unknown", evidence_sha256, evidence_size
    mapped = {
        "Q": "queued",
        "W": "queued",
        "R": "running",
        "B": "running",
        "H": "held",
        "S": "held",
        "E": "exiting",
        "T": "exiting",
        "C": "terminal",
        "F": "terminal",
        "X": "terminal",
    }.get(state, "unknown")
    return mapped, "fresh", evidence_sha256, evidence_size


class RTWinExecutionAdapter:
    """The real RTwin/PBS mechanics behind the unchanged ExecutionPort."""

    def __init__(self) -> None:
        self._driver: _RTWinDriver = _SubprocessRTWinDriver()
        self._lock = Lock()
        self._allocated: set[str] = set()
        self._staged: set[str] = set()
        self._submit_invoked: set[str] = set()
        self._reconciliation_candidates: dict[str, str] = {}

    @classmethod
    def _from_driver(cls, driver: _RTWinDriver) -> RTWinExecutionAdapter:
        value = cls()
        value._driver = driver
        return value

    @property
    def contract_version(self) -> str:
        return "rtwin-pbs-v1"

    def allocate_attempt_workspace(self, snapshot: ExecutionSnapshot) -> str:
        _attest_runtime(snapshot)
        with self._lock:
            if snapshot.attempt_id in self._allocated:
                raise PossiblyEffectfulError(
                    EffectKind.REMOTE_WORKSPACE, "remote-workspace-second-call"
                )
            self._allocated.add(snapshot.attempt_id)
        invocation = _Invocation(
            operation=_operation("allocate"),
            argv=(),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
        )
        result = _invoke_text(self._driver, snapshot, invocation)
        if _text_success(result):
            return snapshot.workspace_binding.remote_attempt_dir
        if (
            result.completion_status == "completed"
            and result.returncode == 17
            and result.stdout == b""
            and result.stderr == b"attempt-workspace-exists\n"
        ):
            raise ConfirmedNoEffectError(
                EffectKind.REMOTE_WORKSPACE, "remote-attempt-workspace-exists"
            )
        raise PossiblyEffectfulError(
            EffectKind.REMOTE_WORKSPACE, "remote-workspace-outcome-ambiguous"
        )

    def transfer_exact_bytes(
        self,
        snapshot: ExecutionSnapshot,
        prepared_input_bytes: bytes,
        pbs_template_bytes: bytes,
    ) -> None:
        _attest_runtime(snapshot)
        try:
            snapshot.prepared_input_binding.verify_bytes(prepared_input_bytes)
            snapshot.pbs_template_binding.verify_bytes(pbs_template_bytes)
        except Exception as exc:
            raise ConfirmedNoEffectError(
                EffectKind.INPUT_TRANSFER, "staged-bytes-differ-from-snapshot"
            ) from exc
        with self._lock:
            if snapshot.attempt_id not in self._allocated:
                raise ConfirmedNoEffectError(
                    EffectKind.INPUT_TRANSFER, "remote-workspace-not-allocated"
                )
            if snapshot.attempt_id in self._staged:
                raise PossiblyEffectfulError(
                    EffectKind.INPUT_TRANSFER, "input-transfer-second-call"
                )
            self._staged.add(snapshot.attempt_id)
        ordered = (
            (
                snapshot.prepared_input_binding.logical_name,
                snapshot.prepared_input_binding.sha256,
                snapshot.prepared_input_binding.size_bytes,
                prepared_input_bytes,
            ),
            (
                snapshot.pbs_template_binding.logical_name,
                snapshot.pbs_template_binding.sha256,
                snapshot.pbs_template_binding.size_bytes,
                pbs_template_bytes,
            ),
        )
        for logical_name, digest, size, content in ordered:
            invocation = _Invocation(
                operation=_operation("stage"),
                argv=(logical_name, digest, str(size)),
                cwd=snapshot.workspace_binding.remote_attempt_dir,
                input_bytes=content,
            )
            result = _invoke_text(self._driver, snapshot, invocation)
            if not _text_success(result):
                raise PossiblyEffectfulError(
                    EffectKind.INPUT_TRANSFER, "input-transfer-outcome-ambiguous"
                )

    def submit_once(self, snapshot: ExecutionSnapshot) -> str:
        _attest_runtime(snapshot)
        with self._lock:
            if snapshot.attempt_id not in self._staged:
                raise ConfirmedNoEffectError(
                    EffectKind.SUBMISSION, "exact-bytes-not-staged"
                )
            if snapshot.attempt_id in self._submit_invoked:
                raise PossiblyEffectfulError(
                    EffectKind.SUBMISSION, "qsub-second-call-refused"
                )
            self._submit_invoked.add(snapshot.attempt_id)
        invocation = _Invocation(
            operation=_operation("qsub"),
            argv=(snapshot.pbs_template_binding.logical_name,),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
        )
        result = _invoke_text(self._driver, snapshot, invocation)
        candidate: str | None = None
        try:
            candidate_text = result.stdout.decode("ascii")
        except UnicodeDecodeError:
            candidate_text = ""
        if candidate_text.endswith("\n") and candidate_text.count("\n") == 1:
            possible = candidate_text[:-1]
            if _JOB_ID.fullmatch(possible):
                candidate = possible
                with self._lock:
                    self._reconciliation_candidates[snapshot.attempt_id] = possible
        if (
            result.completion_status == "completed"
            and result.returncode == 0
            and result.stderr == b""
            and result.eof_stdout
            and result.eof_stderr
            and candidate is not None
        ):
            return candidate
        raise PossiblyEffectfulError(EffectKind.SUBMISSION, "qsub-outcome-ambiguous")

    def reconcile_submission(
        self, snapshot: ExecutionSnapshot, *, effect_sequence: int
    ) -> RemoteEffectReceipt:
        _attest_runtime(snapshot)
        if isinstance(effect_sequence, bool) or not isinstance(effect_sequence, int) or effect_sequence < 1:
            raise TransportBoundaryError("effect_sequence must be a positive integer")
        with self._lock:
            candidate = self._reconciliation_candidates.get(snapshot.attempt_id)
        if candidate is None:
            return RemoteEffectReceipt(
                attempt_id=snapshot.attempt_id,
                execution_snapshot_id=snapshot.execution_snapshot_id,
                submission_intent_id=snapshot.submission_intent_id,
                effect_sequence=effect_sequence,
                effect_kind=EffectKind.SUBMISSION_RECONCILIATION,
                effect_state=EffectState.POSSIBLY_EFFECTFUL,
                remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
                details={"source": "rtwin-read-only", "status": "no-exact-job-id"},
            )
        binding = _internal_binding(snapshot, candidate)
        invocation = _Invocation(
            operation=_operation("qstat"),
            argv=("-f", candidate),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
        )
        try:
            result = self._driver.invoke_text(snapshot, invocation)
        except TransportBoundaryError:
            raise
        except Exception:
            result = _TextResult(
                stdout=b"",
                stderr=b"",
                returncode=None,
                eof_stdout=False,
                eof_stderr=False,
                completion_status="transport-error",
            )
        state, freshness, _digest, _size = _qstat_classification(binding, result)
        if freshness == "fresh" and state not in {"unknown", "absent"}:
            return RemoteEffectReceipt(
                attempt_id=snapshot.attempt_id,
                execution_snapshot_id=snapshot.execution_snapshot_id,
                submission_intent_id=snapshot.submission_intent_id,
                effect_sequence=effect_sequence,
                effect_kind=EffectKind.SUBMISSION_RECONCILIATION,
                effect_state=EffectState.CONFIRMED_EFFECT,
                remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
                job_id=candidate,
                details={"source": "rtwin-qstat-read-only", "state": state},
            )
        return RemoteEffectReceipt(
            attempt_id=snapshot.attempt_id,
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=effect_sequence,
            effect_kind=EffectKind.SUBMISSION_RECONCILIATION,
            effect_state=EffectState.POSSIBLY_EFFECTFUL,
            remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
            details={"source": "rtwin-qstat-read-only", "state": state},
        )


def _internal_binding(snapshot: ExecutionSnapshot, job_id: str) -> ExactRemoteJobBinding:
    """Private reconciliation-only view; never grants public read authority."""

    value = object.__new__(ExactRemoteJobBinding)
    object.__setattr__(value, "attempt_id", snapshot.attempt_id)
    object.__setattr__(value, "execution_snapshot_id", snapshot.execution_snapshot_id)
    object.__setattr__(value, "submission_intent_id", snapshot.submission_intent_id)
    object.__setattr__(value, "remote_effect_receipt_id", "reconciliation-private")
    object.__setattr__(value, "remote_workspace", snapshot.workspace_binding.remote_attempt_dir)
    object.__setattr__(value, "job_id", job_id)
    return value


class RTWinReadAdapter:
    """Read-only scheduler acquisition and exact byte-return fetch."""

    def __init__(self) -> None:
        self._driver: _RTWinDriver = _SubprocessRTWinDriver()
        self._clock: Callable[[], str] = _utc_now

    @classmethod
    def _from_driver(
        cls, driver: _RTWinDriver, *, clock: Callable[[], str] = _utc_now
    ) -> RTWinReadAdapter:
        value = cls()
        value._driver = driver
        value._clock = clock
        return value

    def read_scheduler(
        self,
        snapshot: ExecutionSnapshot,
        binding: ExactRemoteJobBinding,
        current_profile: ServerProfile,
    ) -> SchedulerReadEvidence:
        _assert_binding_matches_snapshot(snapshot, binding, current_profile)
        _attest_runtime(snapshot)
        invocation = _Invocation(
            operation=_operation("qstat"),
            argv=("-f", binding.job_id),
            cwd=binding.remote_workspace,
        )
        try:
            result = self._driver.invoke_text(snapshot, invocation)
        except TransportBoundaryError:
            raise
        except Exception:
            result = _TextResult(
                stdout=b"",
                stderr=b"",
                returncode=None,
                eof_stdout=False,
                eof_stderr=False,
                completion_status="transport-error",
            )
        state, freshness, evidence_sha256, evidence_size = _qstat_classification(
            binding, result
        )
        return SchedulerReadEvidence._from_classified(
            binding=binding,
            observed_at_utc=self._clock(),
            freshness=freshness,
            state=state,
            evidence_sha256=evidence_sha256,
            evidence_size_bytes=evidence_size,
        )

    def fetch_exact_output(
        self,
        snapshot: ExecutionSnapshot,
        binding: ExactRemoteJobBinding,
        current_profile: ServerProfile,
        *,
        input_binding_observation_id: str,
        requests: tuple[ExactArtifactRequest, ...],
        capture_sequence: int,
    ) -> FetchedOutputCapture:
        _assert_binding_matches_snapshot(snapshot, binding, current_profile)
        _attest_runtime(snapshot)
        _validate_requests(requests)
        if isinstance(capture_sequence, bool) or not isinstance(capture_sequence, int) or capture_sequence < 1:
            raise TransportBoundaryError("capture_sequence must be a positive integer")
        if not isinstance(input_binding_observation_id, str) or not input_binding_observation_id.strip():
            raise TransportBoundaryError("input_binding_observation_id is required")
        prepared_name = snapshot.prepared_input_binding.logical_name
        if not prepared_name.endswith(".gjf"):
            raise TransportBoundaryError("prepared input has no frozen Gaussian basename")
        required_log = prepared_name[:-4] + ".log"
        gaussian_logs = tuple(
            item for item in requests if item.artifact_kind == "gaussian-log"
        )
        required = tuple(item for item in requests if item.required)
        if (
            len(gaussian_logs) != 1
            or len(required) != 1
            or required[0].artifact_kind != "gaussian-log"
            or required[0].logical_name != required_log
            or required[0].remote_relative_name != required_log
            or any(
                item.required or item.artifact_kind not in {"stdout", "stderr"}
                for item in requests
                if item is not required[0]
            )
        ):
            raise TransportBoundaryError("fetch must bind the exact required Gaussian log")
        artifacts: list[FetchedArtifact] = []
        status = "captured"
        total = 0
        for request in requests:
            invocation = _Invocation(
                operation=_operation("fetch"),
                argv=(request.remote_relative_name,),
                cwd=binding.remote_workspace,
            )
            try:
                result = self._driver.invoke_fetch(snapshot, invocation)
            except TransportBoundaryError:
                raise
            except Exception:
                result = _FetchResult(status="transport-error")
            if not _is_fetch_result_closed(result):
                raise TransportBoundaryError("fetch driver returned an invalid result")
            if result.status == "missing":
                status = "capture-in-progress"
                break
            if result.status == "transport-error":
                status = "capture-interrupted"
                break
            if result.status != "found":
                raise TransportBoundaryError("fetched source is unstable or malformed")
            content = result.content
            observed_digest = sha256(content).hexdigest()
            if (
                type(content) is not bytes
                or result.before_identity is None
                or result.before_identity != result.after_identity
                or result.before_size != len(content)
                or result.after_size != len(content)
                or result.before_sha256 != observed_digest
                or result.after_sha256 != observed_digest
            ):
                raise TransportBoundaryError("fetched source changed across its bounded read")
            if len(content) > MAX_FETCH_ARTIFACT_BYTES:
                raise TransportBoundaryError("fetched source exceeds the artifact byte cap")
            total += len(content)
            if total > MAX_FETCH_CAPTURE_BYTES:
                raise TransportBoundaryError("fetched capture exceeds the aggregate byte cap")
            artifacts.append(FetchedArtifact(request=request, content=content))
        if not artifacts:
            raise TransportBoundaryError("zero stable artifacts cannot create a capture")
        missing = requests[len(artifacts) :]
        completeness = "complete" if not missing else "partial"
        return FetchedOutputCapture(
            binding=binding,
            input_binding_observation_id=input_binding_observation_id,
            capture_sequence=capture_sequence,
            capture_status=status,
            capture_completeness=completeness,
            requests=requests,
            artifacts=tuple(artifacts),
            missing_requests=missing,
            captured_at_utc=self._clock(),
        )


__all__ = ["RTWinExecutionAdapter", "RTWinReadAdapter"]
