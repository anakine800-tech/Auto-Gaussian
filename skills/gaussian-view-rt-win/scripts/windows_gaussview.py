#!/usr/bin/env python3
"""Reuse one SSH master to verify, transfer, and visibly open a GJF in Windows GaussView."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path

HOST = "<RTWIN_PRIVATE_IP>"
USER = "<WINDOWS_USER>"
TARGET = f"{USER}@{HOST}"
SOCKET = "/tmp/codex-windows-gaussview.sock"
REMOTE_ROOT = r"<WINDOWS_HOME>\Desktop\GaussianProjects"
GVIEW = r"D:\gs\g16\G16W\gview.exe"


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    # Windows OpenSSH may emit localized OEM/GBK bytes. ASCII tokens used for
    # control checks remain intact; replacement avoids locale-dependent crashes.
    return subprocess.run(
        command, check=check, text=True, encoding="utf-8", errors="replace", capture_output=True
    )


def master_ready() -> bool:
    return run(["ssh", "-S", SOCKET, "-O", "check", TARGET], check=False).returncode == 0


def ssh(remote_command: str) -> str:
    return run(["ssh", "-S", SOCKET, TARGET, remote_command]).stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_master() -> int:
    if master_ready():
        print(json.dumps({"master": "ready", "socket": SOCKET, "target": TARGET}))
        return 0
    command = f"ssh -M -S {shlex.quote(SOCKET)} -o ControlPersist=15m -N -f {TARGET}"
    apple = f'tell application "Terminal" to do script {json.dumps(command)}'
    subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate', "-e", apple], check=True)
    print(json.dumps({
        "master": "password_required",
        "terminal_command": command,
        "next": "Enter the Windows account password in Terminal, then rerun this command or use open.",
    }))
    return 0


def open_gjf(source: Path, project: str) -> int:
    if not master_ready():
        raise SystemExit("SSH master is not ready. Run the 'master' subcommand and enter the password once.")
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".gjf", ".com"}:
        raise SystemExit("Input must be an existing .gjf or .com file")
    project = re.sub(r"[^A-Za-z0-9_-]+", "_", project).strip("_")
    if not project:
        raise SystemExit("Project name becomes empty after sanitization")

    remote_dir = REMOTE_ROOT + "\\" + project
    remote_file = remote_dir + "\\" + source.name
    launcher_name = "open_gaussview.cmd"
    remote_launcher = remote_dir + "\\" + launcher_name
    task = "CodexGaussView_" + project[:40]

    ssh(f'powershell -NoProfile -Command "$d=\'{remote_dir}\'; New-Item -ItemType Directory -Force -Path $d | Out-Null; if (-not (Test-Path -LiteralPath \'{GVIEW}\')) {{ exit 41 }}"')
    remote_scp_path = f"{TARGET}:<WINDOWS_HOME>/Desktop/GaussianProjects/{project}/{source.name}"
    run(["scp", "-o", f"ControlPath={SOCKET}", str(source), remote_scp_path])

    local_hash = sha256(source)
    remote_hash = ssh(
        f'powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath \'{remote_file}\').Hash"'
    ).strip().lower()
    if local_hash != remote_hash:
        raise SystemExit(f"SHA-256 mismatch: local={local_hash} remote={remote_hash}")

    launcher = source.parent / f".{project}_{launcher_name}"
    launcher.write_text(f'@echo off\r\nstart "" "{GVIEW}" "{remote_file}"\r\n', encoding="utf-8", newline="")
    try:
        launcher_remote_scp = f"{TARGET}:<WINDOWS_HOME>/Desktop/GaussianProjects/{project}/{launcher_name}"
        run(["scp", "-o", f"ControlPath={SOCKET}", str(launcher), launcher_remote_scp])
        ssh(f"schtasks /Create /TN {task} /TR {remote_launcher} /SC ONCE /ST 23:59 /RU INTERACTIVE /F")
        try:
            ssh(f"schtasks /Run /TN {task}")
        finally:
            ssh(f"schtasks /Delete /TN {task} /F")
    finally:
        launcher.unlink(missing_ok=True)

    processes = ssh('tasklist /FI "IMAGENAME eq gview.exe"')
    if "gview.exe" not in processes or "Console" not in processes:
        raise SystemExit("GaussView was not confirmed in the visible Console session")
    print(json.dumps({
        "opened": True,
        "calculation_started": False,
        "local_file": str(source),
        "remote_file": remote_file,
        "sha256": local_hash,
        "gaussview": GVIEW,
        "session": "Console",
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("master", help="Open or check the reusable SSH master connection")
    sub.add_parser("status", help="Report whether the reusable SSH master is ready")
    open_parser = sub.add_parser("open", help="Transfer, hash-check, and open a Gaussian input")
    open_parser.add_argument("input")
    open_parser.add_argument("--project", required=True)
    args = parser.parse_args()
    if args.command == "master":
        return open_master()
    if args.command == "status":
        print(json.dumps({"master_ready": master_ready(), "socket": SOCKET, "target": TARGET}))
        return 0
    return open_gjf(Path(args.input), args.project)


if __name__ == "__main__":
    raise SystemExit(main())
