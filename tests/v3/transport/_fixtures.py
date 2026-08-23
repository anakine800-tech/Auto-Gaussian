"""Offline Transport fixtures with no process or network calls."""

from __future__ import annotations

from collections import deque
import auto_g16.execution as execution
import auto_g16.transport as transport
from auto_g16.transport._bridge import _BRIDGE_LAUNCHER_BYTES, _SERVER_AGENT_BYTES
from auto_g16.transport._driver import (
    _FetchResult,
    _Invocation,
    _OPERATION_TABLE_BYTES,
    _TextResult,
)
from auto_g16.transport.rtwin import RTWinExecutionAdapter, RTWinReadAdapter

from tests.v3.execution.test_execution import (
    ExecutionFixture,
    INPUT_BYTES,
    TEMPLATE_BYTES,
)


NOW = "2026-08-23T00:00:00.000000Z"
LATER = "2026-08-23T00:01:00.000000Z"


def success(stdout: bytes = b"") -> _TextResult:
    return _TextResult(
        stdout=stdout,
        stderr=b"",
        returncode=0,
        eof_stdout=True,
        eof_stderr=True,
        completion_status="completed",
    )


def found(content: bytes, identity: str = "dev:1:ino:2") -> _FetchResult:
    from hashlib import sha256

    digest = sha256(content).hexdigest()
    return _FetchResult(
        status="found",
        content=content,
        before_identity=identity,
        after_identity=identity,
        before_size=len(content),
        after_size=len(content),
        before_sha256=digest,
        after_sha256=digest,
    )


class FakeDriver:
    def __init__(
        self,
        *,
        text_results: tuple[_TextResult, ...] = (),
        fetch_results: tuple[_FetchResult, ...] = (),
    ) -> None:
        self.text_results = deque(text_results)
        self.fetch_results = deque(fetch_results)
        self.text_calls: list[tuple[execution.ExecutionSnapshot, _Invocation]] = []
        self.fetch_calls: list[tuple[execution.ExecutionSnapshot, _Invocation]] = []

    def invoke_text(
        self, snapshot: execution.ExecutionSnapshot, invocation: _Invocation
    ) -> _TextResult:
        self.text_calls.append((snapshot, invocation))
        if not self.text_results:
            raise AssertionError("unexpected text operation")
        return self.text_results.popleft()

    def invoke_fetch(
        self, snapshot: execution.ExecutionSnapshot, invocation: _Invocation
    ) -> _FetchResult:
        self.fetch_calls.append((snapshot, invocation))
        if not self.fetch_results:
            raise AssertionError("unexpected fetch operation")
        return self.fetch_results.popleft()


class TransportFixture(ExecutionFixture):
    def profile(self, *, wrapper: bytes = _SERVER_AGENT_BYTES) -> execution.ServerProfile:
        executable_bytes = {
            "mac-ssh": b"mac ssh executable bytes",
            "mac-scp": b"mac scp executable bytes",
            "rtwin-bridge": _BRIDGE_LAUNCHER_BYTES,
        }
        executable_paths = {
            name: self.temporary / name for name in executable_bytes
        }
        for name, path in executable_paths.items():
            path.write_bytes(executable_bytes[name])
            if name in {"mac-ssh", "mac-scp", "rtwin-bridge"}:
                path.chmod(0o700)
        runtime = {
            "auto-g16-rtwin-operation-table/1": _OPERATION_TABLE_BYTES,
            "rtwin-pbs-v1": wrapper,
            "mac-ssh": executable_bytes["mac-ssh"],
            "mac-scp": executable_bytes["mac-scp"],
            "rtwin-ssh": b"rtwin ssh executable bytes",
            "rtwin-scp": b"rtwin scp executable bytes",
            "rtwin-bridge": executable_bytes["rtwin-bridge"],
            "server-python": b"server python executable bytes",
            "server-qsub": b"server qsub executable bytes",
            "server-qstat": b"server qstat executable bytes",
        }
        return execution.ServerProfile(
            server_profile_id="profile-transport-1",
            profile_revision=11,
            transport_kind="legacy_rtwin_pbs",
            target_host="10.0.0.50",
            target_port=22,
            remote_user="user100",
            jump_topology=[("100.64.0.1", 22, "rtwin-user")],
            host_key_policy="strict",
            batch_mode=True,
            identities_only=True,
            remote_root=execution.LEGACY_REMOTE_ROOT,
            platform_paths={
                "rtwin_root": r"C:\RTWIN",
                "known_hosts": "/etc/ssh/ssh_known_hosts",
                "mac_ssh_executable": str(executable_paths["mac-ssh"]),
                "mac_scp_executable": str(executable_paths["mac-scp"]),
                "rtwin_ssh_executable": r"C:\Windows\System32\OpenSSH\ssh.exe",
                "rtwin_scp_executable": r"C:\Windows\System32\OpenSSH\scp.exe",
                "rtwin_bridge_executable": str(executable_paths["rtwin-bridge"]),
                "server_python_executable": "/usr/bin/python3",
                "server_qsub_executable": "/usr/bin/qsub",
                "server_qstat_executable": "/usr/bin/qstat",
            },
            config_files=[("ssh_config", b"Host RTwin\n  HostName 100.64.0.1\n")],
            runtime_contents=runtime,
        )

    def transport_snapshot(
        self, *, profile: execution.ServerProfile | None = None
    ) -> tuple[execution.ExecutionSnapshot, execution.ServerProfile]:
        actual_profile = profile or self.profile()
        prepared = execution.PreparedInputBinding(
            attempt_id="attempt-1",
            calculation_plan_id="plan-1",
            calculation_plan_revision=3,
            input_format="gaussian-gjf",
            logical_name="input.gjf",
            prepared_bytes=INPUT_BYTES,
        )
        resource = execution.ResolvedResourceRequest(
            resource_spec=self.store.load_resource_spec("resources-1"),
            cores=8,
            memory_mb=12_288,
            walltime_seconds=3_600,
            queue="simple",
        )
        workspace = execution.WorkspaceBinding(
            project=self.store.load_project("project-1"),
            attempt_id="attempt-1",
            local_approved_root=str(self.local_root),
            local_attempt_dir=str(self.local_project / "attempt-1"),
            rtwin_approved_root=r"C:\RTWIN",
            rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1",
            remote_approved_root=execution.LEGACY_REMOTE_ROOT,
            remote_attempt_dir="/home/user100/SDL/project-1/attempt-1",
        )
        template = execution.PbsTemplateBinding(
            logical_name="job.pbs",
            template_bytes=TEMPLATE_BYTES,
            template_contract_version="pbs-template-v1",
            prepared_input_logical_name="input.gjf",
        )
        snapshot = execution.prepare_execution_snapshot(
            self.store,
            attempt_id="attempt-1",
            calculation_plan_id="plan-1",
            resource_spec_id="resources-1",
            prepared_input_binding=prepared,
            resolved_resource_request=resource,
            resolved_server_profile=execution.resolve_server_profile(actual_profile),
            workspace_binding=workspace,
            pbs_template_binding=template,
            adapter_contract_version="rtwin-pbs-v1",
        )
        return snapshot, actual_profile

    def persisted_binding(
        self,
        snapshot: execution.ExecutionSnapshot,
        profile: execution.ServerProfile,
        *,
        job_id: str = "123.server",
    ) -> transport.ExactRemoteJobBinding:
        journal = execution.ReceiptJournal(self.store)
        receipt = execution.RemoteEffectReceipt(
            attempt_id=snapshot.attempt_id,
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=1,
            effect_kind=execution.EffectKind.SUBMISSION,
            effect_state=execution.EffectState.CONFIRMED_EFFECT,
            remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
            job_id=job_id,
            details={"source": "controlled-fixture"},
        )
        journal.append(receipt)
        return transport.ExactRemoteJobBinding.from_persisted_receipt(
            snapshot,
            journal,
            remote_effect_receipt_id=receipt.remote_effect_receipt_id,
            current_profile=profile,
        )

    @staticmethod
    def execution_adapter(driver: FakeDriver) -> RTWinExecutionAdapter:
        return RTWinExecutionAdapter._from_driver(driver)

    @staticmethod
    def read_adapter(driver: FakeDriver, timestamp: str = NOW) -> RTWinReadAdapter:
        return RTWinReadAdapter._from_driver(driver, clock=lambda: timestamp)


__all__ = [
    "FakeDriver",
    "LATER",
    "NOW",
    "TransportFixture",
    "found",
    "success",
]
