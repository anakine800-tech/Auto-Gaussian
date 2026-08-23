"""Fixed source-controlled RTwin bootstrap and closed AGV3 frame helpers."""

from __future__ import annotations

import base64
from hashlib import sha256
import re
import struct
from typing import Final, Mapping

from ._canonical import TransportBoundaryError, canonical_json_bytes, strict_canonical_json

_BOOTSTRAP_PROTOCOL: Final = "auto-g16-v3-rtwin-bootstrap/2"
_BOOTSTRAP_SOURCE_NAME: Final = "auto-g16-v3-rtwin-bootstrap-v2.py"
_FRAME_MAGIC: Final = b"AGV3"
_TOKEN = re.compile(r"^[A-Za-z0-9_:.\\/ -]+$")

_BOOTSTRAP_SOURCE: Final = r'''from __future__ import annotations
import base64,hashlib,json,os,re,stat,struct,subprocess,sys
MAGIC=b"AGV3"; PROTOCOL="auto-g16-v3-rtwin-bootstrap/2"; FILE_CAP=134217728
DIALECT="auto-g16-v3-pbs-resource-enactment/synthetic-test/1"
OPS={"ALLOCATE_WORKSPACE","STAGE_EXACT_FILE","SUBMIT_QSUB_ONCE","QUERY_SCHEDULER","STAT_EXACT_FILE","FETCH_EXACT_FILE","RECONCILE_SUBMISSION"}
PORTABLE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$"); JOB=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ENV={"LANG":"C","LC_ALL":"C","PYTHONNOUSERSITE":"1","PYTHONUTF8":"1"}
def die(message,code=2): sys.stderr.buffer.write((message+"\n").encode("ascii")); raise SystemExit(code)
def canonical(value): return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
def decode64(value):
    if type(value) is not str: die("invalid-base64")
    try: raw=base64.b64decode(value.encode("ascii"),validate=True)
    except Exception: die("invalid-base64")
    if base64.b64encode(raw).decode("ascii")!=value: die("invalid-base64")
    return raw
def decode64_bounded(value,cap):
    if type(value) is not str or len(value)>4*((cap+2)//3): die("invalid-base64")
    raw=decode64(value)
    if len(raw)>cap: die("invalid-base64")
    return raw
def encode64(value): return base64.b64encode(value).decode("ascii")
def read_frame():
    head=sys.stdin.buffer.read(12)
    if len(head)!=12 or head[:4]!=MAGIC: die("invalid-frame")
    size=struct.unpack(">Q",head[4:])[0]
    if size>179306484: die("frame-too-large")
    raw=sys.stdin.buffer.read(size)
    if len(raw)!=size or sys.stdin.buffer.read(1): die("invalid-frame")
    try: value=json.loads(raw.decode("utf-8"))
    except Exception: die("invalid-frame")
    if canonical(value)!=raw or type(value) is not dict or set(value)!={"binding","operation","payload","protocol"}: die("invalid-frame")
    if value["protocol"]!=PROTOCOL or value["operation"] not in OPS or type(value["binding"]) is not dict or type(value["payload"]) is not dict: die("invalid-frame")
    return value
def respond(operation,result):
    raw=canonical({"operation":operation,"protocol":PROTOCOL,"result":result,"status":"ok"})
    sys.stdout.buffer.write(MAGIC+struct.pack(">Q",len(raw))+raw)
def regular_identity(path,expected_size,expected_digest):
    try:
        before=os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_mode&0o111==0 or before.st_size!=expected_size: die("runtime-drift")
        flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0); fd=os.open(path,flags)
        try:
            opened=os.fstat(fd); digest=hashlib.sha256(); remaining=opened.st_size
            if not stat.S_ISREG(opened.st_mode) or opened.st_mode&0o111==0: die("runtime-drift")
            while remaining:
                chunk=os.read(fd,min(65536,remaining))
                if not chunk: die("runtime-drift")
                digest.update(chunk); remaining-=len(chunk)
            named=os.lstat(path)
            if not stat.S_ISREG(named.st_mode) or named.st_mode&0o111==0 or (opened.st_dev,opened.st_ino)!=(named.st_dev,named.st_ino) or digest.hexdigest()!=expected_digest: die("runtime-drift")
        finally: os.close(fd)
    except OSError: die("runtime-drift")
    return opened.st_dev,opened.st_ino
def token(value):
    raw=decode64(value)
    if not 1<=len(raw)<=4096: die("invalid-token")
    return raw
def workspace_token(fd,b):
    s=os.fstat(fd); return canonical(["auto-g16-workspace-token/1",b["attempt_id"],b["execution_snapshot_id"],b["submission_intent_id"],b["remote_workspace"],s.st_dev,s.st_ino])
def open_workspace(binding,create=False):
    root=binding["remote_workspace"].rsplit("/",2)[0]; project,attempt=binding["remote_workspace"].rsplit("/",2)[1:]
    if not root.startswith("/") or not PORTABLE.fullmatch(project) or not PORTABLE.fullmatch(attempt) or attempt!=binding["attempt_id"]: die("unsafe-workspace")
    flags=os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    rootfd=os.open(root,flags); projectfd=os.open(project,flags,dir_fd=rootfd)
    try:
        if create:
            try: os.mkdir(attempt,0o700,dir_fd=projectfd)
            except FileExistsError: die("attempt-workspace-exists",17)
        attemptfd=os.open(attempt,flags,dir_fd=projectfd)
    except BaseException: os.close(projectfd); os.close(rootfd); raise
    if not create and token(binding["workspace_physical_token_base64"])!=workspace_token(attemptfd,binding): die("workspace-drift")
    return rootfd,projectfd,attemptfd
def closefds(values):
    for value in reversed(values): os.close(value)
def artifact_token(fd,b,p):
    s=os.fstat(fd); return canonical(["auto-g16-artifact-token/1",b["workspace_authority_id"],p["artifact_kind"],p["logical_name"],p["sha256"],p["size_bytes"],s.st_dev,s.st_ino])
def artifact_from_token(identity,b,kind):
    raw=token(identity)
    try: value=json.loads(raw.decode("utf-8"))
    except Exception: die("artifact-drift")
    if canonical(value)!=raw or type(value) is not list or len(value)!=8 or value[0]!="auto-g16-artifact-token/1" or value[1]!=b["workspace_authority_id"] or value[2]!=kind or type(value[3]) is not str or not PORTABLE.fullmatch(value[3]) or type(value[4]) is not str or not re.fullmatch(r"[0-9a-f]{64}",value[4]) or type(value[5]) is not int or value[5]<0 or type(value[6]) is not int or type(value[7]) is not int: die("artifact-drift")
    return value
def attest_artifact(fd,b,kind,identity):
    value=artifact_from_token(identity,b,kind); name=value[3]
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0); af=os.open(name,flags,dir_fd=fd)
    try:
        s=os.fstat(af); content,digest=read_bounded(af,s.st_size,"artifact-drift")
        payload={"artifact_kind":kind,"logical_name":name,"sha256":digest.hexdigest(),"size_bytes":s.st_size}
        if value[4]!=payload["sha256"] or value[5]!=payload["size_bytes"] or value[6]!=s.st_dev or value[7]!=s.st_ino or token(identity)!=artifact_token(af,b,payload): die("artifact-drift")
    finally: os.close(af)
    return name
def manifest():
    try: raw=base64.b64decode(sys.argv[1].encode("ascii"),validate=True); value=json.loads(raw.decode("utf-8"))
    except Exception: die("invalid-manifest")
    if canonical(value)!=raw: die("invalid-manifest")
    roots=value["trust_roots"]
    for name in ("server_python","server_qsub","server_qstat"):
        item=roots[name]; regular_identity(item["path"],item["expected_size_bytes"],item["expected_sha256"])
    if os.path.abspath(sys.executable)!=roots["server_python"]["path"]: die("server-python-path-drift")
    return roots
def read_bounded(fd,expected_size,label):
    if type(expected_size) is not int or expected_size<0 or expected_size>FILE_CAP: die(label)
    content=bytearray(); digest=hashlib.sha256(); remaining=expected_size
    while remaining:
        amount=min(65536,remaining)
        if len(content)+amount>FILE_CAP: die(label)
        chunk=os.read(fd,amount)
        if not chunk: die(label)
        content.extend(chunk); digest.update(chunk); remaining-=len(chunk)
    if os.read(fd,1): die(label)
    return bytes(content),digest
def run_exact(root,args,cwd_fd,capout,caperr):
    path=root["path"]; before=regular_identity(path,root["expected_size_bytes"],root["expected_sha256"])
    completed=subprocess.run([path,*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=f"/proc/self/fd/{cwd_fd}",env=ENV,shell=False,timeout=30,check=False)
    after=regular_identity(path,root["expected_size_bytes"],root["expected_sha256"])
    if before!=after: die("runtime-drift")
    if len(completed.stdout)>capout or len(completed.stderr)>caperr: die("child-output-overflow")
    return completed
def main():
    roots=manifest(); request=read_frame(); op=request["operation"]; b=request["binding"]; p=request["payload"]
    base={"transport_store_id","store_instance_id","runtime_attestation_id","attempt_id","execution_snapshot_id","submission_intent_id","remote_workspace"}
    stage=base|{"workspace_authority_id","workspace_physical_token_base64"}
    submitted=stage|{"prepared_input_artifact_authority_id","prepared_input_artifact_physical_token_base64","pbs_template_artifact_authority_id","pbs_template_artifact_physical_token_base64"}
    query=stage|{"job_authority_id","receipt_binding_id","remote_effect_receipt_id","job_id"}
    if not base.issubset(b) or any(type(b[k]) is not str or not b[k] for k in base): die("invalid-binding")
    if op=="ALLOCATE_WORKSPACE":
        if set(b)!=base or p: die("invalid-request")
        fds=open_workspace(b,True)
        try: result={"remote_workspace":b["remote_workspace"],"workspace_physical_token_base64":encode64(workspace_token(fds[2],b))}
        finally: closefds(fds)
        return respond(op,result)
    if "workspace_authority_id" not in b or "workspace_physical_token_base64" not in b: die("invalid-binding")
    fds=open_workspace(b)
    try:
        fd=fds[2]
        if op=="STAGE_EXACT_FILE":
            if set(b)!=stage or set(p)!={"artifact_kind","logical_name","remote_relative_name","sha256","size_bytes","content_base64"} or p["artifact_kind"] not in {"prepared-input","pbs-template"} or p["logical_name"]!=p["remote_relative_name"] or not PORTABLE.fullmatch(p["logical_name"]): die("invalid-request")
            if type(p["size_bytes"]) is not int or p["size_bytes"]<0 or p["size_bytes"]>FILE_CAP: die("invalid-content")
            content=decode64_bounded(p["content_base64"],FILE_CAP)
            if len(content)!=p["size_bytes"] or hashlib.sha256(content).hexdigest()!=p["sha256"]: die("invalid-content")
            flags=os.O_RDWR|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0); af=os.open(p["logical_name"],flags,0o400,dir_fd=fd)
            try:
                pos=0
                while pos<len(content): pos+=os.write(af,content[pos:])
                os.fsync(af); written=os.fstat(af)
                if written.st_size>FILE_CAP: die("invalid-content")
                os.lseek(af,0,os.SEEK_SET); reread,digest=read_bounded(af,written.st_size,"invalid-content")
                if reread!=content or digest.hexdigest()!=p["sha256"]: die("invalid-content")
                result={k:p[k] for k in ("artifact_kind","logical_name","remote_relative_name","sha256","size_bytes")}; result["artifact_physical_token_base64"]=encode64(artifact_token(af,b,p))
            finally: os.close(af)
            return respond(op,result)
        if op=="SUBMIT_QSUB_ONCE":
            if set(b)!=submitted or set(p)!={"pbs_basename","resource_enactment"} or not PORTABLE.fullmatch(p["pbs_basename"]): die("invalid-request")
            r=p["resource_enactment"]
            if not isinstance(r,dict) or set(r)!={"execution_snapshot_id","resolved_resource_request_id","cores","memory_mb","walltime_seconds","queue","scheduler_dialect_id"}: die("invalid-request")
            if type(r["execution_snapshot_id"]) is not str or not r["execution_snapshot_id"] or r["execution_snapshot_id"]!=b["execution_snapshot_id"] or type(r["resolved_resource_request_id"]) is not str or not r["resolved_resource_request_id"]: die("invalid-request")
            if any(type(r[k]) is not int or r[k]<1 for k in ("cores","memory_mb","walltime_seconds")): die("invalid-request")
            if r["queue"] is not None and (type(r["queue"]) is not str or not PORTABLE.fullmatch(r["queue"])): die("invalid-request")
            if r["scheduler_dialect_id"]!=DIALECT: die("unknown-resource-dialect")
            attest_artifact(fd,b,"prepared-input",b["prepared_input_artifact_physical_token_base64"])
            pbs_name=attest_artifact(fd,b,"pbs-template",b["pbs_template_artifact_physical_token_base64"])
            if pbs_name!=p["pbs_basename"]: die("artifact-drift")
            args=["--auto-g16-synthetic-cores",str(r["cores"]),"--auto-g16-synthetic-memory-mb",str(r["memory_mb"]),"--auto-g16-synthetic-walltime-seconds",str(r["walltime_seconds"])]
            if r["queue"] is not None: args.extend(["--auto-g16-synthetic-queue",r["queue"]])
            args.append(p["pbs_basename"])
            die("non-production-resource-dialect")
            completed=run_exact(roots["server_qsub"],args,fd,65536,65536)
            if completed.returncode!=0 or completed.stderr: die("qsub-failed")
            try: job=completed.stdout.decode("ascii").strip()
            except UnicodeDecodeError: die("invalid-job-id")
            if not JOB.fullmatch(job) or completed.stdout!=job.encode("ascii")+b"\n": die("invalid-job-id")
            return respond(op,{"job_id":job})
        if op=="QUERY_SCHEDULER":
            if set(b)!=query or set(p)!={"job_id"} or p["job_id"]!=b.get("job_id") or not JOB.fullmatch(p["job_id"]): die("invalid-request")
            completed=run_exact(roots["server_qstat"],["-f",p["job_id"]],fd,262144,65536)
            return respond(op,{"stdout_base64":encode64(completed.stdout),"stderr_base64":encode64(completed.stderr),"returncode":completed.returncode,"eof_stdout":True,"eof_stderr":True,"completion_status":"completed"})
        if op in {"STAT_EXACT_FILE","FETCH_EXACT_FILE"}:
            if set(b)!=query: die("invalid-binding")
            name=p.get("remote_relative_name")
            if not isinstance(name,str) or not PORTABLE.fullmatch(name): die("invalid-request")
            flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
            try: af=os.open(name,flags,dir_fd=fd)
            except FileNotFoundError:
                if op=="STAT_EXACT_FILE": return respond(op,{"presence":"absent","remote_relative_name":name})
                die("artifact-not-found",44)
            try:
                before=os.fstat(af)
                if before.st_size>FILE_CAP: die("artifact-too-large")
                content,digest=read_bounded(af,before.st_size,"short-read")
                after=os.fstat(af); physical=canonical(["auto-g16-fetched-file-token/1",b["workspace_authority_id"],name,before.st_dev,before.st_ino,before.st_size])
                if (before.st_dev,before.st_ino,before.st_size)!=(after.st_dev,after.st_ino,after.st_size): die("unstable-file")
            finally: os.close(af)
            if op=="STAT_EXACT_FILE": return respond(op,{"presence":"present","remote_relative_name":name,"size_bytes":len(content),"file_physical_token_base64":encode64(physical)})
            if set(p)!={"remote_relative_name","expected_size_bytes","expected_file_physical_token_base64"} or p["expected_size_bytes"]!=len(content) or token(p["expected_file_physical_token_base64"])!=physical: die("file-drift")
            return respond(op,{"remote_relative_name":name,"size_bytes":len(content),"sha256":digest.hexdigest(),"content_base64":encode64(content),"file_physical_token_base64":encode64(physical),"eof":True})
        if op=="RECONCILE_SUBMISSION":
            if set(b)!=submitted or set(p)!={"effect_sequence"} or type(p["effect_sequence"]) is not int or p["effect_sequence"]<1: die("invalid-request")
            return respond(op,{"effect_state":"possibly_effectful"})
        die("invalid-operation")
    finally: closefds(fds)
main()
'''
_BOOTSTRAP_SOURCE_BYTES: Final = _BOOTSTRAP_SOURCE.encode("utf-8")
_BOOTSTRAP_SOURCE_SHA256: Final = sha256(_BOOTSTRAP_SOURCE_BYTES).hexdigest()
_BOOTSTRAP_SOURCE_SIZE: Final = 15195
_BOOTSTRAP_SOURCE_LF_COUNT: Final = 201
_BOOTSTRAP_SOURCE_EXPECTED_SHA256: Final = "3f3653a8b13d4cb5a5f5ba6e9caa02c3049caf144af13fd4491674c1fc7eb2f3"
if (
    len(_BOOTSTRAP_SOURCE_BYTES) != _BOOTSTRAP_SOURCE_SIZE
    or _BOOTSTRAP_SOURCE_SHA256 != _BOOTSTRAP_SOURCE_EXPECTED_SHA256
    or _BOOTSTRAP_SOURCE_BYTES.count(b"\n") != _BOOTSTRAP_SOURCE_LF_COUNT
    or b"\r" in _BOOTSTRAP_SOURCE_BYTES
    or b"\x00" in _BOOTSTRAP_SOURCE_BYTES
    or not _BOOTSTRAP_SOURCE_BYTES.startswith(b"from __future__ import annotations\n")
    or not _BOOTSTRAP_SOURCE_BYTES.endswith(b"main()\n")
):
    raise RuntimeError("source-controlled bootstrap source identity drifted")

def _encode_frame(value: Mapping[str, object]) -> bytes:
    raw = canonical_json_bytes(dict(value)); return _FRAME_MAGIC + struct.pack(">Q", len(raw)) + raw

def _decode_frame(raw: bytes, *, cap: int, field: str) -> Mapping[str, object]:
    if type(raw) is not bytes or len(raw) < 12 or len(raw) > cap or raw[:4] != _FRAME_MAGIC:
        raise TransportBoundaryError(f"{field} frame is invalid")
    size = struct.unpack(">Q", raw[4:12])[0]; body = raw[12:]
    if size != len(body): raise TransportBoundaryError(f"{field} frame length is invalid")
    value = strict_canonical_json(body, field)
    if not isinstance(value, dict): raise TransportBoundaryError(f"{field} is not an object")
    return value

def _encode_request_frame(request: Mapping[str, object], *, cap: int) -> bytes:
    if set(request) != {"binding", "operation", "payload", "protocol"} or request.get("protocol") != _BOOTSTRAP_PROTOCOL:
        raise TransportBoundaryError("bootstrap request shape is invalid")
    framed = _encode_frame(request)
    if len(framed) > cap: raise TransportBoundaryError("bootstrap request exceeds cap")
    return framed

def _decode_response_frame(raw: bytes, *, operation: str, cap: int) -> Mapping[str, object]:
    value = _decode_frame(raw, cap=cap, field="bootstrap response")
    if set(value) != {"operation", "protocol", "result", "status"} or value.get("operation") != operation or value.get("protocol") != _BOOTSTRAP_PROTOCOL or value.get("status") != "ok" or not isinstance(value.get("result"), dict):
        raise TransportBoundaryError("bootstrap response shape is invalid")
    return value["result"]  # type: ignore[return-value]

def _posix_quote_v1(token: str) -> str:
    if type(token) is not str or any(c in token for c in "\x00\r\n"): raise TransportBoundaryError("POSIX token contains control data")
    return "'" + token.replace("'", "'\"'\"'") + "'"

def _posix_quote_bootstrap_source_v1(source: str) -> str:
    if type(source) is not str or not source.isascii() or "\x00" in source or "\r" in source:
        raise TransportBoundaryError("fixed bootstrap source is invalid")
    return "'" + source.replace("'", "'\"'\"'") + "'"

def _powershell_quote_v1(token: str) -> str:
    if any(c in token for c in "\x00\r\n"): raise TransportBoundaryError("PowerShell token contains control data")
    return "'" + token.replace("'", "''") + "'"

def _powershell_quote_fixed_launcher_v1(launcher: str) -> str:
    if type(launcher) is not str or not launcher.isascii() or "\x00" in launcher or "\r" in launcher:
        raise TransportBoundaryError("fixed PowerShell launcher is invalid")
    return "'" + launcher.replace("'", "''") + "'"

def _cmd_quote_v1(token: str) -> str:
    if _TOKEN.fullmatch(token) is None or any(c in token for c in '"%!^&|<>()\x00\r\n'):
        raise TransportBoundaryError("cmd-v1 token is outside the closed grammar")
    return '"' + token + '"'

def _crt_quote(token: str) -> str:
    if "\x00" in token: raise TransportBoundaryError("CRT token contains NUL")
    if token and not any(c in token for c in ' \t"'): return token
    result='"'; slashes=0
    for character in token:
        if character=='\\': slashes+=1; continue
        if character=='"': result+='\\'*(slashes*2+1)+'"'; slashes=0; continue
        result+='\\'*slashes+character; slashes=0
    return result+'\\'*(slashes*2)+'"'

def _build_rtwin_command(snapshot: object, manifest: object) -> tuple[str, ...]:
    roots=manifest.trust_roots; grammar=roots["rtwin_remote_shell"].shell_grammar
    if grammar=="cmd-v1": _cmd_quote_v1(roots["rtwin_ssh"].path); raise TransportBoundaryError("cmd-v1 cannot attest RTwin executables under nine-root v1")
    if grammar!="powershell-v1": raise TransportBoundaryError("unsupported RTwin shell grammar")
    target=snapshot.resolved_server_profile.target_identity; manifest_arg=base64.b64encode(manifest.raw_bytes).decode("ascii")
    server_tokens=(roots["server_python"].path,"-I","-S","-B","-c")
    server_command=" ".join(
        (*(_posix_quote_v1(item) for item in server_tokens),
         _posix_quote_bootstrap_source_v1(_BOOTSTRAP_SOURCE),
         _posix_quote_v1(manifest_arg))
    )
    inner=["-o","BatchMode=yes","-o","IdentitiesOnly=yes","-p",str(target["destination_port"]),f"{snapshot.resolved_server_profile.remote_user}@{target['destination_host']}","--",server_command]
    arguments=" ".join(_crt_quote(item) for item in inner); ssh=_powershell_quote_v1(roots["rtwin_ssh"].path); scp=_powershell_quote_v1(roots["rtwin_scp"].path)
    script=("$ErrorActionPreference='Stop';function Test-AutoG16([string]$p,[long]$s,[string]$h){$f=Get-Item -LiteralPath $p -Force;if($f.PSIsContainer -or (($f.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0) -or $f.Length-ne$s){exit 97};$x=(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant();if($x-ne$h){exit 97}};"
            f"Test-AutoG16 {ssh} {roots['rtwin_ssh'].expected_size_bytes} '{roots['rtwin_ssh'].expected_sha256}';Test-AutoG16 {scp} {roots['rtwin_scp'].expected_size_bytes} '{roots['rtwin_scp'].expected_sha256}';"
            "$p=New-Object System.Diagnostics.Process;$p.StartInfo.UseShellExecute=$false;"+f"$p.StartInfo.FileName={ssh};$p.StartInfo.Arguments={_powershell_quote_fixed_launcher_v1(arguments)};"+"$p.StartInfo.RedirectStandardInput=$true;$p.StartInfo.RedirectStandardOutput=$true;$p.StartInfo.RedirectStandardError=$true;$p.Start()|Out-Null;$i=[Console]::OpenStandardInput().CopyToAsync($p.StandardInput.BaseStream);$o=$p.StandardOutput.BaseStream.CopyToAsync([Console]::OpenStandardOutput());$e=$p.StandardError.BaseStream.CopyToAsync([Console]::OpenStandardError());$i.GetAwaiter().GetResult();$p.StandardInput.Close();$p.WaitForExit();$o.GetAwaiter().GetResult();$e.GetAwaiter().GetResult();exit $p.ExitCode")
    jump=target["jump_topology"]
    if not jump: raise TransportBoundaryError("RTwin hop is required")
    rtwin=jump[-1]; proxies=jump[:-1]
    command=[roots["mac_ssh"].path,"-o","BatchMode=yes","-o","IdentitiesOnly=yes","-p",str(rtwin["port"])]
    if proxies: command.extend(["-J",",".join(f"{x['user']}@{x['host']}:{x['port']}" for x in proxies)])
    command.extend(["--",f"{rtwin['user']}@{rtwin['host']}",script]); return tuple(command)

__all__=["_BOOTSTRAP_PROTOCOL","_BOOTSTRAP_SOURCE","_BOOTSTRAP_SOURCE_BYTES","_BOOTSTRAP_SOURCE_NAME","_BOOTSTRAP_SOURCE_SHA256","_build_rtwin_command","_cmd_quote_v1","_crt_quote","_decode_response_frame","_encode_request_frame","_posix_quote_bootstrap_source_v1","_posix_quote_v1","_powershell_quote_fixed_launcher_v1","_powershell_quote_v1"]
