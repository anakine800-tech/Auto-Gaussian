"""Offline Transport fixtures with no process or network calls."""

from __future__ import annotations

from collections import deque
from hashlib import sha256

import auto_g16.execution as execution
import auto_g16.transport as transport
from auto_g16.transport._bridge import (
    _BOOTSTRAP_PROTOCOL,
    _BOOTSTRAP_SOURCE_BYTES,
    _BOOTSTRAP_SOURCE_NAME,
    _RTWIN_LAUNCHER_BYTES,
    _RTWIN_LAUNCHER_NAME,
)
from auto_g16.transport._canonical import canonical_json_bytes
from auto_g16.transport._driver import (
    _FetchResult,
    _Invocation,
    _MANIFEST_NAME,
    _OPERATION_TABLE_BYTES,
    _RESOURCE_DESCRIPTOR_NAME,
    _SYNTHETIC_RESOURCE_DIALECT,
    _TORQUE_RESOURCE_DIALECT,
    _TABLE_NAME,
    _resolve_deployment_authority,
)
from auto_g16.transport.rtwin import RTWinExecutionAdapter, RTWinReadAdapter
from tests.v3.execution.test_execution import ExecutionFixture, INPUT_BYTES, TEMPLATE_BYTES

NOW = "2026-08-23T00:00:00.000000Z"
LATER = "2026-08-23T00:01:00.000000Z"
RESOURCE_DESCRIPTOR_BYTES = canonical_json_bytes({
    "schema": "auto-g16-v3-pbs-resource-enactment/1",
    "dialect": _SYNTHETIC_RESOURCE_DIALECT,
})
TORQUE_RESOURCE_DESCRIPTOR_BYTES = canonical_json_bytes({
    "schema": "auto-g16-v3-pbs-resource-enactment/1",
    "dialect": _TORQUE_RESOURCE_DIALECT,
})


def _manifest_bytes(
    mac_ssh_path: str,
    mac_scp_path: str,
    *,
    mac_ssh_bytes: bytes,
    mac_scp_bytes: bytes,
    deployment_id: str = "synthetic-rtwin-deployment-v1",
    windows_grammar: str = "cmd-powershell-launcher-v1",
    torque_executables: bool = False,
) -> bytes:
    def file_root(path: str, platform: str, mode: str, identity: str, content: bytes) -> dict[str, object]:
        return {
            "attestation_mode": mode,
            "deployment_identity": identity,
            "expected_sha256": sha256(content).hexdigest(),
            "expected_size_bytes": len(content),
            "path": path,
            "platform": platform,
            "shell_grammar": None,
        }

    roots: dict[str, object] = {
        "mac_ssh": file_root(mac_ssh_path, "macos", "controller-file-v1", "synthetic-mac-ssh", mac_ssh_bytes),
        "mac_scp": file_root(mac_scp_path, "macos", "controller-file-v1", "synthetic-mac-scp", mac_scp_bytes),
        "rtwin_ssh": file_root(r"C:\Windows\System32\OpenSSH\ssh.exe", "windows", "rtwin-shell-file-v1", "synthetic-rtwin-ssh", b"rtwin ssh executable bytes"),
        "rtwin_scp": file_root(r"C:\Windows\System32\OpenSSH\scp.exe", "windows", "rtwin-shell-file-v1", "synthetic-rtwin-scp", b"rtwin scp executable bytes"),
        "rtwin_launcher": file_root("C:\\AutoG16Runtime\\" + _RTWIN_LAUNCHER_NAME, "windows", "rtwin-shell-file-v1", "auto-g16-v3-rtwin-launcher-v2", _RTWIN_LAUNCHER_BYTES),
        "rtwin_remote_shell": {
            "attestation_mode": "deployment-root-v1",
            "deployment_identity": "synthetic-windows-shell",
            "expected_sha256": None,
            "expected_size_bytes": None,
            "path": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "platform": "windows",
            "shell_grammar": windows_grammar,
        },
        "server_remote_shell": {
            "attestation_mode": "deployment-root-v1",
            "deployment_identity": "synthetic-posix-shell",
            "expected_sha256": None,
            "expected_size_bytes": None,
            "path": "/bin/sh",
            "platform": "posix",
            "shell_grammar": "posix-sh-v1",
        },
        "server_python": file_root("/usr/bin/python3", "posix", "server-self-check-v1", "synthetic-python", b"python"),
        "server_qsub": file_root("/usr/bin/qsub", "posix", "server-python-file-v1", "synthetic-qsub", b"qsub"),
        "server_qstat": file_root("/usr/bin/qstat", "posix", "server-python-file-v1", "synthetic-qstat", b"qstat"),
    }
    if torque_executables:
        roots["server_qsub"] = {
            **roots["server_qsub"],
            "deployment_identity": "torque-6.1.0-qsub-preflight",
            "expected_sha256": "f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d",
            "expected_size_bytes": 418_920,
            "path": "/usr/local/bin/qsub",
        }
        roots["server_qstat"] = {
            **roots["server_qstat"],
            "deployment_identity": "torque-6.1.0-qstat-preflight",
            "expected_sha256": "3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a",
            "expected_size_bytes": 185_656,
            "path": "/usr/local/bin/qstat",
        }
    return canonical_json_bytes({
        "bootstrap_protocol": _BOOTSTRAP_PROTOCOL,
        "deployment_id": deployment_id,
        "schema": "auto-g16-v3-transport-deployment-manifest/2",
        "trust_roots": roots,
    })


def response(operation: str, result: dict[str, object]):
    from auto_g16.transport._driver import _TextResult
    return _TextResult(
        stdout=canonical_json_bytes(result),
        stderr=b"",
        returncode=0,
        eof_stdout=True,
        eof_stderr=True,
        completion_status="completed",
    )


def qstat(stdout: bytes, *, stderr: bytes = b"", returncode: int = 0):
    from auto_g16.transport._driver import _TextResult
    return _TextResult(stdout=stdout, stderr=stderr, returncode=returncode, eof_stdout=True, eof_stderr=True, completion_status="completed")


def found(content: bytes, identity: str = "ZmlsZS10b2tlbi12MQ==") -> _FetchResult:
    digest = sha256(content).hexdigest()
    return _FetchResult(status="found", content=content, before_identity=identity, after_identity=identity, before_size=len(content), after_size=len(content), before_sha256=digest, after_sha256=digest)


class FakeDriver:
    def __init__(self, *, text_results: tuple[object, ...] = (), fetch_results: tuple[_FetchResult, ...] = ()) -> None:
        self.text_results = deque(text_results)
        self.fetch_results = deque(fetch_results)
        self.text_calls: list[tuple[execution.ExecutionSnapshot, _Invocation]] = []
        self.fetch_calls: list[tuple[execution.ExecutionSnapshot, _Invocation]] = []

    def invoke_text(self, snapshot: execution.ExecutionSnapshot, invocation: _Invocation):
        self.text_calls.append((snapshot, invocation))
        if not self.text_results:
            raise AssertionError("unexpected text operation")
        return self.text_results.popleft()

    def invoke_fetch(self, snapshot: execution.ExecutionSnapshot, invocation: _Invocation) -> _FetchResult:
        self.fetch_calls.append((snapshot, invocation))
        if not self.fetch_results:
            raise AssertionError("unexpected fetch operation")
        return self.fetch_results.popleft()


class TransportFixture(ExecutionFixture):
    def setUp(self) -> None:
        super().setUp()
        store_root = self.temporary / "transport-store"
        store_root.mkdir()
        self.transport_database = store_root / "transport.sqlite3"
        self.transport_store = transport.TransportStore.create_new(self.transport_database, approved_root=store_root)
        self.addCleanup(self.transport_store.close)
        self.mac_ssh_config = self.temporary / "mac-ssh-config"
        self.mac_known_hosts = self.temporary / "mac-known-hosts"

    def profile(self, *, deployment_id: str = "synthetic-rtwin-deployment-v2", windows_grammar: str = "cmd-powershell-launcher-v1", jump_topology: list[tuple[str, int, str]] | None = None, resource_descriptor: bytes = RESOURCE_DESCRIPTOR_BYTES) -> execution.ServerProfile:
        executable_bytes = {"mac-ssh": b"mac ssh executable bytes", "mac-scp": b"mac scp executable bytes"}
        executable_paths = {name: self.temporary / name for name in executable_bytes}
        for name, path in executable_paths.items():
            path.write_bytes(executable_bytes[name])
            path.chmod(0o700)
        self.mac_known_hosts.write_bytes(b"rtwin-a ssh-ed25519 AAAAC3NzaSyntheticHostKey\n")
        mac_config=(
            "Host rtwin-a\n"
            "  HostName 100.64.0.1\n"
            "  Port 22\n"
            "  User rtwin-user\n"
            "  IdentityFile /keys/mac-rtwin\n"
            "  IdentitiesOnly yes\n"
            "  StrictHostKeyChecking yes\n"
            f"  UserKnownHostsFile {self.mac_known_hosts}\n"
        ).encode("utf-8")
        self.mac_ssh_config.write_bytes(mac_config)
        rtwin_known_path=r"C:\Config\server-known"
        rtwin_config=(
            "Host server-a\n"
            "  HostName 10.0.0.50\n"
            "  Port 22\n"
            "  User user100\n"
            "  IdentityFile C:\\Keys\\server\n"
            "  IdentitiesOnly yes\n"
            "  StrictHostKeyChecking yes\n"
            f"  UserKnownHostsFile {rtwin_known_path}\n"
        ).encode("utf-8")
        rtwin_known=b"server-a ssh-ed25519 AAAAC3NzaSyntheticServerKey\n"
        manifest = _manifest_bytes(str(executable_paths["mac-ssh"]), str(executable_paths["mac-scp"]), mac_ssh_bytes=executable_bytes["mac-ssh"], mac_scp_bytes=executable_bytes["mac-scp"], deployment_id=deployment_id, windows_grammar=windows_grammar, torque_executables=resource_descriptor==TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        return execution.ServerProfile(
            server_profile_id="profile-transport-1", profile_revision=11, transport_kind="legacy_rtwin_pbs",
            target_host="10.0.0.50", target_port=22, remote_user="user100",
            jump_topology=[("100.64.0.1", 22, "rtwin-user")] if jump_topology is None else jump_topology, host_key_policy="strict",
            batch_mode=True, identities_only=True, remote_root=execution.LEGACY_REMOTE_ROOT,
            platform_paths={
                "rtwin_root": r"C:\RTWIN", "known_hosts": "/etc/ssh/ssh_known_hosts",
                "mac_ssh_config_path": str(self.mac_ssh_config), "mac_known_hosts_path": str(self.mac_known_hosts),
                "rtwin_ssh_config_path": r"C:\Config\server-ssh-config", "rtwin_known_hosts_path": rtwin_known_path,
                "rtwin_bootstrap_source_path": r"C:\AutoG16Runtime\auto-g16-v3-rtwin-bootstrap-v2-py36.py",
                "rtwin_deployment_manifest_path": r"C:\AutoG16Runtime\transport-deployment-manifest-v2.json",
            },
            config_files=[
                ("mac-ssh-config",mac_config),("mac-known-hosts",self.mac_known_hosts.read_bytes()),
                ("rtwin-ssh-config",rtwin_config),("rtwin-known-hosts",rtwin_known),
            ],
            runtime_contents={_MANIFEST_NAME: manifest, _TABLE_NAME: _OPERATION_TABLE_BYTES, _BOOTSTRAP_SOURCE_NAME: _BOOTSTRAP_SOURCE_BYTES, _RESOURCE_DESCRIPTOR_NAME: resource_descriptor},
        )

    def transport_snapshot(self, *, profile: execution.ServerProfile | None = None, prepared_bytes: bytes = INPUT_BYTES, cores: int = 8, memory_mb: int = 12_288, walltime_seconds: int = 3_600, queue: str | None = "simple") -> tuple[execution.ExecutionSnapshot, execution.ServerProfile]:
        actual_profile = profile or self.profile()
        prepared = execution.PreparedInputBinding(attempt_id="attempt-1", calculation_plan_id="plan-1", calculation_plan_revision=3, input_format="gaussian-gjf", logical_name="input.gjf", prepared_bytes=prepared_bytes)
        resource = execution.ResolvedResourceRequest(resource_spec=self.store.load_resource_spec("resources-1"), cores=cores, memory_mb=memory_mb, walltime_seconds=walltime_seconds, queue=queue)
        workspace = execution.WorkspaceBinding(project=self.store.load_project("project-1"), attempt_id="attempt-1", local_approved_root=str(self.local_root), local_attempt_dir=str(self.local_project / "attempt-1"), rtwin_approved_root=r"C:\RTWIN", rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1", remote_approved_root=execution.LEGACY_REMOTE_ROOT, remote_attempt_dir="/home/user100/SDL/project-1/attempt-1")
        template = execution.PbsTemplateBinding(logical_name="job.pbs", template_bytes=TEMPLATE_BYTES, template_contract_version="pbs-template-v1", prepared_input_logical_name="input.gjf")
        snapshot = execution.prepare_execution_snapshot(self.store, attempt_id="attempt-1", calculation_plan_id="plan-1", resource_spec_id="resources-1", prepared_input_binding=prepared, resolved_resource_request=resource, resolved_server_profile=execution.resolve_server_profile(actual_profile), workspace_binding=workspace, pbs_template_binding=template, adapter_contract_version="rtwin-pbs-v1")
        return snapshot, actual_profile

    def seed_physical_authority(self, snapshot: execution.ExecutionSnapshot, profile: execution.ServerProfile, *, job_id: str = "123.server") -> None:
        authority = _resolve_deployment_authority(snapshot, profile)
        runtime = self.transport_store._runtime(snapshot, authority)
        workspace = self.transport_store._record_workspace(snapshot, runtime["runtime_attestation_id"], b"workspace-token-v1")
        for kind, bound in (("prepared-input", snapshot.prepared_input_binding), ("pbs-template", snapshot.pbs_template_binding)):
            self.transport_store._record_artifact(snapshot, runtime["runtime_attestation_id"], workspace["workspace_authority_id"], kind=kind, logical_name=bound.logical_name, digest=bound.sha256, size=bound.size_bytes, token=canonical_json_bytes({"logical_name": bound.logical_name, "token": f"{kind}-token-v1"}))
        self.transport_store._record_job(snapshot, runtime["runtime_attestation_id"], workspace["workspace_authority_id"], job_id)

    def persisted_binding(self, snapshot: execution.ExecutionSnapshot, profile: execution.ServerProfile, *, job_id: str = "123.server") -> transport.ExactRemoteJobBinding:
        self.seed_physical_authority(snapshot, profile, job_id=job_id)
        journal = execution.ReceiptJournal(self.store)
        receipt = execution.RemoteEffectReceipt(attempt_id=snapshot.attempt_id, execution_snapshot_id=snapshot.execution_snapshot_id, submission_intent_id=snapshot.submission_intent_id, effect_sequence=1, effect_kind=execution.EffectKind.SUBMISSION, effect_state=execution.EffectState.CONFIRMED_EFFECT, remote_workspace=snapshot.workspace_binding.remote_attempt_dir, job_id=job_id, details={"source": "controlled-fixture"})
        journal.append(receipt)
        return transport.ExactRemoteJobBinding.from_persisted_receipt(snapshot, journal, remote_effect_receipt_id=receipt.remote_effect_receipt_id, current_profile=profile, transport_store=self.transport_store)

    def execution_adapter(self, driver: FakeDriver, profile: execution.ServerProfile) -> RTWinExecutionAdapter:
        return RTWinExecutionAdapter._from_driver(driver, transport_store=self.transport_store, current_profile=profile)

    def read_adapter(self, driver: FakeDriver, timestamp: str = NOW) -> RTWinReadAdapter:
        return RTWinReadAdapter._from_driver(driver, transport_store=self.transport_store, clock=lambda: timestamp)


__all__ = ["FakeDriver", "LATER", "NOW", "RESOURCE_DESCRIPTOR_BYTES", "TORQUE_RESOURCE_DESCRIPTOR_BYTES", "TransportFixture", "found", "qstat", "response"]
