"""Source-controlled two-hop RTwin bridge mechanics.

This module is deliberately package-private.  The tiny launcher bytes are the
reviewed ``rtwin-bridge`` executable installed on the Mac.  It starts exactly
one strict Mac-to-RTwin SSH process.  That process starts the attested RTwin
SSH executable, which runs the source-controlled server agent below.  Caller
bytes can occupy stdin only; no caller can supply an executable, command, or
shell fragment.
"""

from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from typing import BinaryIO, Final, Mapping
import zlib


_BRIDGE_LAUNCHER_BYTES: Final = (
    b"#!/usr/bin/env python3\n"
    b"from auto_g16.transport._bridge import main\n"
    b"raise SystemExit(main())\n"
)

# The agent is self-contained because it is executed on the PBS server.  It
# accepts one canonical JSON packet encoded with URL-safe base64.  Filesystem
# mutation is descriptor-relative and no-follow; qsub/qstat are fixed argv
# subprocesses; fetch reads the same opened regular file twice and returns one
# framed immutable byte result.
_SERVER_AGENT_SOURCE: Final = r'''from __future__ import annotations
import base64, hashlib, json, os, re, selectors, signal, stat, subprocess, sys, tempfile, time

ENV={"LANG":"C","LC_ALL":"C","PYTHONNOUSERSITE":"1","PYTHONUTF8":"1"}
PORTABLE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
JOB=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_ARTIFACT=134217728

def die(message, code=2):
    sys.stderr.buffer.write((message+"\n").encode("ascii")); raise SystemExit(code)

def portable(value):
    return isinstance(value,str) and value not in {".",".."} and PORTABLE.fullmatch(value) is not None

def decode_packet(raw):
    try:
        data=base64.urlsafe_b64decode(raw.encode("ascii")); value=json.loads(data.decode("utf-8"))
    except Exception: die("invalid-agent-request")
    required={"schema","operation","argv","remote_root","cwd","server_python_executable","server_qsub_executable","server_qstat_executable","runtime_identities"}
    if type(value) is not dict or set(value)!=required or value["schema"]!="auto-g16-rtwin-server-agent/1": die("invalid-agent-request")
    if type(value["argv"]) is not list or any(type(x) is not str for x in value["argv"]): die("invalid-agent-request")
    root=value["remote_root"]; cwd=value["cwd"]
    if type(root) is not str or type(cwd) is not str or not root.startswith("/") or not cwd.startswith(root+"/"): die("unsafe-workspace")
    relative=cwd[len(root)+1:].split("/")
    if len(relative)!=2 or not all(portable(x) for x in relative): die("unsafe-workspace")
    value["relative"]=relative
    return value

def runtime_identity(value,name):
    identities=value["runtime_identities"]
    if type(identities) is not dict or type(identities.get(name)) is not dict or set(identities[name])!={"sha256","size_bytes"}: die("invalid-runtime-identity")
    identity=identities[name]
    if re.fullmatch(r"[0-9a-f]{64}",identity["sha256"]) is None or type(identity["size_bytes"]) is not int or identity["size_bytes"]<1: die("invalid-runtime-identity")
    return identity

def attested_copy(path,identity,require_executable=True):
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    fd=os.open(path,flags)
    try:
        opened=os.fstat(fd); named=os.stat(path,follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode) or (opened.st_dev,opened.st_ino)!=(named.st_dev,named.st_ino) or opened.st_size!=identity["size_bytes"] or (require_executable and opened.st_mode&0o111==0): die("runtime-executable-drift")
        content=read_exact(fd,opened.st_size)
        if hashlib.sha256(content).hexdigest()!=identity["sha256"]: die("runtime-executable-drift")
        named_after=os.stat(path,follow_symlinks=False)
        if (named_after.st_dev,named_after.st_ino)!=(opened.st_dev,opened.st_ino): die("runtime-executable-replaced")
        sealed=tempfile.TemporaryFile(mode="w+b"); sealed.write(content); sealed.flush(); os.fsync(sealed.fileno()); os.fchmod(sealed.fileno(),0o500); sealed.seek(0); return sealed
    finally: os.close(fd)

def open_directory(path):
    flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    fd=os.open(path,flags)
    if not stat.S_ISDIR(os.fstat(fd).st_mode): os.close(fd); die("unsafe-workspace")
    return fd

def open_workspace(value, create=False):
    root_fd=open_directory(value["remote_root"]); project_fd=-1; attempt_fd=-1
    try:
        project,attempt=value["relative"]
        flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
        project_fd=os.open(project,flags,dir_fd=root_fd)
        project_named=os.stat(project,dir_fd=root_fd,follow_symlinks=False)
        project_opened=os.fstat(project_fd)
        if not stat.S_ISDIR(project_named.st_mode) or (project_named.st_dev,project_named.st_ino)!=(project_opened.st_dev,project_opened.st_ino): die("unsafe-workspace")
        if create:
            try: os.mkdir(attempt,mode=0o700,dir_fd=project_fd)
            except FileExistsError: die("attempt-workspace-exists",17)
            created=os.stat(attempt,dir_fd=project_fd,follow_symlinks=False)
        attempt_fd=os.open(attempt,flags,dir_fd=project_fd)
        named=os.stat(attempt,dir_fd=project_fd,follow_symlinks=False); opened=os.fstat(attempt_fd)
        if not stat.S_ISDIR(named.st_mode) or (named.st_dev,named.st_ino)!=(opened.st_dev,opened.st_ino): die("unsafe-workspace")
        if create and (created.st_dev,created.st_ino)!=(opened.st_dev,opened.st_ino): die("attempt-workspace-replaced")
        return root_fd,project_fd,attempt_fd
    except BaseException:
        for fd in (attempt_fd,project_fd,root_fd):
            if fd>=0:
                try: os.close(fd)
                except OSError: pass
        raise

def close_all(*fds):
    for fd in fds:
        try: os.close(fd)
        except OSError: pass

def bounded_process(executable,identity,argv,cwd_fd,stdout_cap,stderr_cap,timeout):
    sealed=attested_copy(executable,identity)
    proc=subprocess.Popen([executable,*argv],executable=f"/proc/self/fd/{sealed.fileno()}",cwd=f"/proc/self/fd/{cwd_fd}",env=ENV,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(cwd_fd,sealed.fileno()),start_new_session=True)
    sel=selectors.DefaultSelector(); buffers={"stdout":bytearray(),"stderr":bytearray()}; eof={"stdout":False,"stderr":False}
    for name,stream in (("stdout",proc.stdout),("stderr",proc.stderr)):
        os.set_blocking(stream.fileno(),False); sel.register(stream,selectors.EVENT_READ,name)
    deadline=time.monotonic()+timeout
    failed=False
    while sel.get_map():
        remaining=deadline-time.monotonic()
        if remaining<=0: failed=True; break
        for key,_mask in sel.select(min(remaining,0.1)):
            name=key.data; cap=stdout_cap if name=="stdout" else stderr_cap
            chunk=os.read(key.fileobj.fileno(),min(65536,cap-len(buffers[name])+1))
            if not chunk: eof[name]=True; sel.unregister(key.fileobj); continue
            buffers[name].extend(chunk)
            if len(buffers[name])>cap: failed=True; break
        if failed: break
    if failed:
        try: os.killpg(proc.pid,signal.SIGKILL)
        except OSError: pass
    try: returncode=proc.wait(timeout=1)
    except Exception:
        try: proc.kill()
        except OSError: pass
        returncode=None
    sealed.close()
    if failed or not all(eof.values()): die("bounded-child-failed")
    return returncode,bytes(buffers["stdout"]),bytes(buffers["stderr"])

def read_exact(fd,size):
    parts=[]; remaining=size
    while remaining:
        chunk=os.read(fd,min(65536,remaining))
        if not chunk: die("short-input")
        parts.append(chunk); remaining-=len(chunk)
    if os.read(fd,1): die("long-input")
    return b"".join(parts)

def main():
    if len(sys.argv)!=2: die("invalid-agent-request")
    value=decode_packet(sys.argv[1]); operation=value["operation"]; argv=value["argv"]
    if sys.executable!=value["server_python_executable"]: die("server-python-path-drift")
    python_copy=attested_copy(sys.executable,runtime_identity(value,"server-python")); python_copy.close()
    if operation=="mkdir-attempt":
        if argv: die("invalid-operation-argv")
        fds=open_workspace(value,create=True); close_all(*fds); return
    fds=open_workspace(value); workspace_fd=fds[2]
    try:
        if operation=="stage-exact-bytes":
            if len(argv)!=3 or not portable(argv[0]) or re.fullmatch(r"[0-9a-f]{64}",argv[1]) is None or re.fullmatch(r"0|[1-9][0-9]*",argv[2]) is None: die("invalid-operation-argv")
            size=int(argv[2])
            flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
            fd=os.open(argv[0],flags,0o400,dir_fd=workspace_fd)
            try:
                digest=hashlib.sha256(); remaining=size
                while remaining:
                    chunk=os.read(sys.stdin.fileno(),min(65536,remaining))
                    if not chunk: die("short-input")
                    digest.update(chunk); remaining-=len(chunk); written=0
                    while written<len(chunk): written+=os.write(fd,chunk[written:])
                if os.read(sys.stdin.fileno(),1): die("long-input")
                os.fsync(fd)
            finally: os.close(fd)
            if digest.hexdigest()!=argv[1]: die("staged-byte-digest-mismatch")
            return
        if operation=="qsub":
            if len(argv)!=1 or not portable(argv[0]): die("invalid-operation-argv")
            rc,out,err=bounded_process(value["server_qsub_executable"],runtime_identity(value,"server-qsub"),argv,workspace_fd,65536,65536,30)
        elif operation=="qstat":
            if len(argv)!=2 or argv[0]!="-f" or JOB.fullmatch(argv[1]) is None: die("invalid-operation-argv")
            rc,out,err=bounded_process(value["server_qstat_executable"],runtime_identity(value,"server-qstat"),argv,workspace_fd,262144,65536,30)
        elif operation=="fetch-exact-bytes":
            if len(argv)!=1 or not portable(argv[0]): die("invalid-operation-argv")
            flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
            try: fd=os.open(argv[0],flags,dir_fd=workspace_fd)
            except FileNotFoundError: die("artifact-not-found",44)
            try:
                before=os.fstat(fd)
                named=os.stat(argv[0],dir_fd=workspace_fd,follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(named.st_mode) or (before.st_dev,before.st_ino)!=(named.st_dev,named.st_ino) or before.st_size>MAX_ARTIFACT: die("unstable-artifact")
                first=read_exact(fd,before.st_size); first_digest=hashlib.sha256(first).hexdigest()
                os.lseek(fd,0,os.SEEK_SET); second=read_exact(fd,before.st_size); second_digest=hashlib.sha256(second).hexdigest(); after=os.fstat(fd); named_after=os.stat(argv[0],dir_fd=workspace_fd,follow_symlinks=False)
                identity=f"{before.st_dev}:{before.st_ino}:{before.st_mode}:{before.st_mtime_ns}"
                identity_after=f"{after.st_dev}:{after.st_ino}:{after.st_mode}:{after.st_mtime_ns}"
                if first!=second or first_digest!=second_digest or identity!=identity_after or (after.st_dev,after.st_ino)!=(named_after.st_dev,named_after.st_ino) or after.st_size!=before.st_size: die("unstable-artifact")
                header=f"AUTO-G16-FETCH/1\nidentity={identity}\nsize={before.st_size}\nsha256={first_digest}\n\n".encode("ascii")
                sys.stdout.buffer.write(header); sys.stdout.buffer.write(first); return
            finally: os.close(fd)
        else: die("unknown-operation")
        sys.stdout.buffer.write(out); sys.stderr.buffer.write(err); raise SystemExit(rc)
    finally: close_all(*fds)

if __name__=="__main__": main()
'''
_SERVER_AGENT_BYTES: Final = _SERVER_AGENT_SOURCE.encode("utf-8")

_PORTABLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _runtime_identity(packet: Mapping[str, object], name: str) -> Mapping[str, object]:
    identities = packet.get("runtime_identities")
    if not isinstance(identities, dict):
        raise ValueError("bridge request lacks runtime identities")
    value = identities.get(name)
    if (
        not isinstance(value, dict)
        or set(value) != {"sha256", "size_bytes"}
        or not isinstance(value.get("sha256"), str)
        or _DIGEST.fullmatch(value["sha256"]) is None
        or isinstance(value.get("size_bytes"), bool)
        or not isinstance(value.get("size_bytes"), int)
        or value["size_bytes"] < 1
    ):
        raise ValueError(f"bridge runtime identity {name} is malformed")
    return value


def _validate_request(packet: object) -> dict[str, object]:
    required = {
        "schema",
        "operation",
        "argv",
        "cwd",
        "remote_root",
        "attempt_id",
        "execution_snapshot_id",
        "submission_intent_id",
        "target_identity",
        "remote_user",
        "platform_paths",
        "runtime_identities",
    }
    if not isinstance(packet, dict) or set(packet) != required:
        raise ValueError("bridge request shape is not closed")
    if packet["schema"] != "auto-g16-rtwin-bridge-request/1":
        raise ValueError("bridge request schema differs")
    operation = packet["operation"]
    argv = packet["argv"]
    if not isinstance(operation, str) or not isinstance(argv, list) or any(
        not isinstance(item, str) for item in argv
    ):
        raise ValueError("bridge operation is malformed")
    validators = {
        "mkdir-attempt": lambda values: not values,
        "stage-exact-bytes": lambda values: len(values) == 3
        and _PORTABLE.fullmatch(values[0]) is not None
        and _DIGEST.fullmatch(values[1]) is not None
        and re.fullmatch(r"0|[1-9][0-9]*", values[2]) is not None,
        "qsub": lambda values: len(values) == 1
        and _PORTABLE.fullmatch(values[0]) is not None,
        "qstat": lambda values: len(values) == 2
        and values[0] == "-f"
        and _JOB_ID.fullmatch(values[1]) is not None,
        "fetch-exact-bytes": lambda values: len(values) == 1
        and _PORTABLE.fullmatch(values[0]) is not None,
    }
    if operation not in validators or not validators[operation](argv):
        raise ValueError("bridge operation is outside the fixed table")
    target = packet["target_identity"]
    paths = packet["platform_paths"]
    identities = packet["runtime_identities"]
    path_names = {
        "rtwin_root",
        "known_hosts",
        "mac_ssh_executable",
        "mac_scp_executable",
        "rtwin_ssh_executable",
        "rtwin_scp_executable",
        "server_python_executable",
        "server_qsub_executable",
        "server_qstat_executable",
    }
    identity_names = {
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
    }
    if (
        not isinstance(target, dict)
        or set(target) != {"destination_host", "destination_port", "jump_topology"}
        or not isinstance(target["destination_host"], str)
        or isinstance(target["destination_port"], bool)
        or not isinstance(target["destination_port"], int)
        or not 1 <= target["destination_port"] <= 65_535
        or not isinstance(target["jump_topology"], list)
        or len(target["jump_topology"]) != 1
        or not isinstance(paths, dict)
        or set(paths) != path_names
        or any(not isinstance(value, str) or not value for value in paths.values())
        or not isinstance(identities, dict)
        or set(identities) != identity_names
    ):
        raise ValueError("bridge target is not one exact RTwin hop")
    jump = target["jump_topology"][0]
    if (
        not isinstance(jump, dict)
        or set(jump) != {"host", "port", "user"}
        or not isinstance(jump["host"], str)
        or isinstance(jump["port"], bool)
        or not isinstance(jump["port"], int)
        or not 1 <= jump["port"] <= 65_535
        or not isinstance(jump["user"], str)
        or _PORTABLE.fullmatch(jump["user"]) is None
        or not isinstance(packet["remote_user"], str)
        or _PORTABLE.fullmatch(packet["remote_user"]) is None
    ):
        raise ValueError("bridge hop identity is malformed")
    remote_root = packet["remote_root"]
    cwd = packet["cwd"]
    if (
        not isinstance(remote_root, str)
        or not isinstance(cwd, str)
        or not cwd.startswith(remote_root + "/")
        or cwd[len(remote_root) + 1 :].split("/")[-1] != packet["attempt_id"]
        or len(cwd[len(remote_root) + 1 :].split("/")) != 2
        or any(
            _PORTABLE.fullmatch(part) is None
            for part in cwd[len(remote_root) + 1 :].split("/")
        )
    ):
        raise ValueError("bridge workspace binding is malformed")
    for name in identity_names:
        _runtime_identity(packet, name)
    if _runtime_identity(packet, "auto-g16-rtwin-operation-table/1") != {
        "sha256": "3502638017454526cdbfee01de47a543a9870c9c57697e4373732cb7909a71d1",
        "size_bytes": 1040,
    }:
        raise ValueError("operation table identity differs")
    if _runtime_identity(packet, "rtwin-bridge") != {
        "sha256": sha256(_BRIDGE_LAUNCHER_BYTES).hexdigest(),
        "size_bytes": len(_BRIDGE_LAUNCHER_BYTES),
    }:
        raise ValueError("bridge launcher identity differs")
    agent_identity = _runtime_identity(packet, "rtwin-pbs-v1")
    if agent_identity != {
        "sha256": sha256(_SERVER_AGENT_BYTES).hexdigest(),
        "size_bytes": len(_SERVER_AGENT_BYTES),
    }:
        raise ValueError("server agent bytes differ from rtwin-pbs-v1 authority")
    return packet


def _powershell_script(packet: Mapping[str, object]) -> str:
    target = packet["target_identity"]
    paths = packet["platform_paths"]
    assert isinstance(target, dict) and isinstance(paths, dict)
    agent_packet = {
        "schema": "auto-g16-rtwin-server-agent/1",
        "operation": packet["operation"],
        "argv": packet["argv"],
        "remote_root": packet["remote_root"],
        "cwd": packet["cwd"],
        "server_python_executable": paths["server_python_executable"],
        "server_qsub_executable": paths["server_qsub_executable"],
        "server_qstat_executable": paths["server_qstat_executable"],
        "runtime_identities": {
            name: packet["runtime_identities"][name]
            for name in ("server-python", "server-qsub", "server-qstat")
        },
    }
    encoded_packet = base64.urlsafe_b64encode(
        json.dumps(agent_packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    inner_argv = [
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-p",
        str(target["destination_port"]),
        f"{packet['remote_user']}@{target['destination_host']}",
        "--",
        str(paths["server_python_executable"]),
        "-c",
        (
            "import base64,sys,zlib;"
            "s=zlib.decompress(base64.urlsafe_b64decode(sys.argv[1]));"
            "sys.argv=[sys.argv[0],sys.argv[2]];"
            "exec(compile(s,"
            "'<auto-g16-rtwin-server-agent>','exec'))"
        ),
        base64.urlsafe_b64encode(zlib.compress(_SERVER_AGENT_BYTES, level=9)).decode(
            "ascii"
        ),
        encoded_packet,
    ]
    arguments = subprocess.list2cmdline(inner_argv).replace("'", "''")
    executable = str(paths["rtwin_ssh_executable"]).replace("'", "''")
    rtwin_identity = packet["runtime_identities"]["rtwin-ssh"]
    assert isinstance(rtwin_identity, dict)
    return (
        "$ErrorActionPreference='Stop';"
        "$f=Get-Item -LiteralPath '" + executable + "' -Force;"
        "if(($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){exit 97};"
        f"if($f.Length -ne {rtwin_identity['size_bytes']}){{exit 97}};"
        "$h=(Get-FileHash -Algorithm SHA256 -LiteralPath '"
        + executable
        + "').Hash.ToLower();"
        f"if($h -ne '{rtwin_identity['sha256']}'){{exit 97}};"
        "$p=New-Object System.Diagnostics.Process;"
        "$p.StartInfo.FileName='" + executable + "';"
        "$p.StartInfo.Arguments='" + arguments + "';"
        "$p.StartInfo.UseShellExecute=$false;"
        "$p.StartInfo.RedirectStandardInput=$true;"
        "$p.StartInfo.RedirectStandardOutput=$true;"
        "$p.StartInfo.RedirectStandardError=$true;"
        "[void]$p.Start();"
        "$i=[Console]::OpenStandardInput().CopyToAsync($p.StandardInput.BaseStream);"
        "$o=$p.StandardOutput.BaseStream.CopyToAsync([Console]::OpenStandardOutput());"
        "$e=$p.StandardError.BaseStream.CopyToAsync([Console]::OpenStandardError());"
        "$i.GetAwaiter().GetResult();$p.StandardInput.Close();"
        "$p.WaitForExit();$o.GetAwaiter().GetResult();$e.GetAwaiter().GetResult();"
        "exit $p.ExitCode"
    )


def _outer_command(packet: Mapping[str, object]) -> tuple[str, ...]:
    target = packet["target_identity"]
    paths = packet["platform_paths"]
    assert isinstance(target, dict) and isinstance(paths, dict)
    jump = target["jump_topology"][0]
    if not isinstance(jump, dict):
        raise ValueError("RTwin hop is malformed")
    encoded = base64.b64encode(_powershell_script(packet).encode("utf-16le")).decode(
        "ascii"
    )
    return (
        str(paths["mac_ssh_executable"]),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={paths['known_hosts']}",
        "-p",
        str(jump["port"]),
        f"{jump['user']}@{jump['host']}",
        "--",
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        encoded,
    )


def _attested_local_executable(
    packet: Mapping[str, object], *, path_name: str, identity_name: str
) -> BinaryIO:
    paths = packet["platform_paths"]
    assert isinstance(paths, dict)
    path = paths[path_name]
    if not isinstance(path, str):
        raise ValueError("local executable path is malformed")
    identity = _runtime_identity(packet, identity_name)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or opened.st_mode & 0o111 == 0
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or opened.st_size != identity["size_bytes"]
        ):
            raise ValueError("local executable identity drifted")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise ValueError("local executable read was short")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("local executable grew during attestation")
        content = b"".join(chunks)
        if sha256(content).hexdigest() != identity["sha256"]:
            raise ValueError("local executable digest drifted")
        named_after = os.stat(path, follow_symlinks=False)
        if (named_after.st_dev, named_after.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise ValueError("local executable was replaced")
        sealed = tempfile.TemporaryFile(mode="w+b")
        sealed.write(content)
        sealed.flush()
        os.fsync(sealed.fileno())
        os.fchmod(sealed.fileno(), 0o500)
        sealed.seek(0)
        return sealed
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    result_fd: int | None = None
    if len(arguments) == 4 and arguments[2] == "--result-fd":
        try:
            result_fd = int(arguments[3], 10)
        except ValueError:
            return 2
        arguments = arguments[:2]
    if len(arguments) != 2 or arguments[0] != "--request-json":
        return 2
    try:
        packet = _validate_request(json.loads(arguments[1]))
        command = _outer_command(packet)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 2
    fetch = packet["operation"] == "fetch-exact-bytes"
    if fetch != (result_fd is not None):
        return 2
    stdout: int | None = result_fd if fetch else None
    try:
        sealed = _attested_local_executable(
            packet, path_name="mac_ssh_executable", identity_name="mac-ssh"
        )
    except (OSError, ValueError):
        return 2
    try:
        completed = subprocess.Popen(
            command,
            executable=f"/dev/fd/{sealed.fileno()}",
            pass_fds=(sealed.fileno(),),
            stdin=None,
            stdout=stdout,
            stderr=None,
            env={
                "LANG": "C",
                "LC_ALL": "C",
                "PYTHONNOUSERSITE": "1",
                "PYTHONUTF8": "1",
            },
            shell=False,
            close_fds=True,
        )
        return completed.wait()
    finally:
        sealed.close()


__all__ = [
    "_BRIDGE_LAUNCHER_BYTES",
    "_SERVER_AGENT_BYTES",
    "_outer_command",
    "_validate_request",
    "main",
]
