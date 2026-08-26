"""Fixed source-controlled RTwin bootstrap and closed AGV3 frame helpers."""

from __future__ import annotations

import base64
from hashlib import sha256
import re
import struct
from typing import Final, Mapping

from ._canonical import TransportBoundaryError, canonical_json_bytes, strict_canonical_json

_BOOTSTRAP_PROTOCOL: Final = "auto-g16-v3-rtwin-bootstrap/2"
_BOOTSTRAP_SOURCE_NAME: Final = "auto-g16-v3-rtwin-bootstrap-v2-py36.py"
_FRAME_MAGIC: Final = b"AGV3"
_TOKEN = re.compile(r"^[A-Za-z0-9_:.\\/ -]+$")

_BOOTSTRAP_SOURCE: Final = r'''import base64,hashlib,json,os,re,stat,struct,subprocess,sys
MAGIC=b"AGV3"; PROTOCOL="auto-g16-v3-rtwin-bootstrap/2"; FILE_CAP=134217728
SYNTHETIC_DIALECT="auto-g16-v3-pbs-resource-enactment/synthetic-test/1"
TORQUE_DIALECT="auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1"
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
            if r["scheduler_dialect_id"] not in {SYNTHETIC_DIALECT,TORQUE_DIALECT}: die("unknown-resource-dialect")
            attest_artifact(fd,b,"prepared-input",b["prepared_input_artifact_physical_token_base64"])
            pbs_name=attest_artifact(fd,b,"pbs-template",b["pbs_template_artifact_physical_token_base64"])
            if pbs_name!=p["pbs_basename"]: die("artifact-drift")
            if r["scheduler_dialect_id"]==SYNTHETIC_DIALECT:
                args=["--auto-g16-synthetic-cores",str(r["cores"]),"--auto-g16-synthetic-memory-mb",str(r["memory_mb"]),"--auto-g16-synthetic-walltime-seconds",str(r["walltime_seconds"])]
                if r["queue"] is not None: args.extend(["--auto-g16-synthetic-queue",r["queue"]])
                args.append(p["pbs_basename"]); die("non-production-resource-dialect")
            if r["queue"]!="batch": die("invalid-torque-queue")
            args=["-l","nodes=1:ppn="+str(r["cores"])+",mem="+str(r["memory_mb"])+"mb,walltime="+str(r["walltime_seconds"]),"-q","batch",p["pbs_basename"]]
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
_BOOTSTRAP_SOURCE_SIZE: Final = 15562
_BOOTSTRAP_SOURCE_LF_COUNT: Final = 203
_BOOTSTRAP_SOURCE_EXPECTED_SHA256: Final = "ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae"
if (
    len(_BOOTSTRAP_SOURCE_BYTES) != _BOOTSTRAP_SOURCE_SIZE
    or _BOOTSTRAP_SOURCE_SHA256 != _BOOTSTRAP_SOURCE_EXPECTED_SHA256
    or _BOOTSTRAP_SOURCE_BYTES.count(b"\n") != _BOOTSTRAP_SOURCE_LF_COUNT
    or b"\r" in _BOOTSTRAP_SOURCE_BYTES
    or b"\x00" in _BOOTSTRAP_SOURCE_BYTES
    or not _BOOTSTRAP_SOURCE_BYTES.startswith(b"import base64,hashlib,json,os,re,stat,struct,subprocess,sys\n")
    or not _BOOTSTRAP_SOURCE_BYTES.endswith(b"main()\n")
):
    raise RuntimeError("source-controlled bootstrap source identity drifted")

_RTWIN_LAUNCHER_NAME: Final = "auto-g16-v3-rtwin-launcher-v4.ps1"
_RTWIN_LAUNCHER_SOURCE: Final = r'''param(
 [Parameter(Mandatory=$true)][string]$ManifestPath,
 [Parameter(Mandatory=$true)][long]$ManifestSize,
 [Parameter(Mandatory=$true)][string]$ManifestSha256,
 [Parameter(Mandatory=$true)][string]$BootstrapPath,
 [Parameter(Mandatory=$true)][long]$BootstrapSize,
 [Parameter(Mandatory=$true)][string]$BootstrapSha256,
 [Parameter(Mandatory=$true)][string]$ConfigPath,
 [Parameter(Mandatory=$true)][long]$ConfigSize,
 [Parameter(Mandatory=$true)][string]$ConfigSha256,
 [Parameter(Mandatory=$true)][string]$KnownHostsPath,
 [Parameter(Mandatory=$true)][long]$KnownHostsSize,
 [Parameter(Mandatory=$true)][string]$KnownHostsSha256,
 [Parameter(Mandatory=$true)][string]$ServerAlias,
 [Parameter(Mandatory=$true)][int]$ServerPort,
 [Parameter(Mandatory=$true)][string]$ServerUser,
 [Parameter(Mandatory=$true)][int]$ExpectedInnerLength,
 [Parameter(Mandatory=$true)][string]$ExpectedInnerSha256
)
$ErrorActionPreference='Stop'
$Utf8=New-Object System.Text.UTF8Encoding($false,$true)
function Fail-AutoG16 { exit 97 }
function Read-AutoG16([string]$Path,[long]$Size,[string]$Digest) {
 $Item=Get-Item -LiteralPath $Path -Force
 if($Item.PSIsContainer -or (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0) -or $Item.Length-ne$Size){Fail-AutoG16}
 $Bytes=[IO.File]::ReadAllBytes($Path)
 if($Bytes.Length-ne$Size){Fail-AutoG16}
 $Hasher=[Security.Cryptography.SHA256]::Create()
 try{$Actual=([BitConverter]::ToString($Hasher.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant()}finally{$Hasher.Dispose()}
 if($Actual-ne$Digest){Fail-AutoG16}
 return ,$Bytes
}
function Read-ExactAutoG16([IO.Stream]$Stream,[byte[]]$Buffer,[int]$Offset,[int]$Count) {
 $Position=0
 while($Position-lt$Count){
  try{$Read=$Stream.Read($Buffer,$Offset+$Position,$Count-$Position)}catch{Fail-AutoG16}
  if($Read-le 0){Fail-AutoG16}
  $Position+=$Read
 }
}
function Quote-Posix([string]$Value) {
 if($Value.IndexOf([char]0)-ge 0 -or $Value.IndexOf("`r")-ge 0 -or $Value.IndexOf("`n")-ge 0){Fail-AutoG16}
 $Sq=[char]39;$Dq=[char]34
 return [string]$Sq+$Value.Replace([string]$Sq,[string]$Sq+$Dq+$Sq+$Dq+$Sq)+$Sq
}
function Quote-PosixFixedBootstrap([byte[]]$Bytes) {
 if($Bytes.Length-ne 15562){Fail-AutoG16}
 $Hasher=[Security.Cryptography.SHA256]::Create()
 try{$Actual=([BitConverter]::ToString($Hasher.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant()}finally{$Hasher.Dispose()}
 if($Actual-ne'ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae'){Fail-AutoG16}
 try{$Value=$Utf8.GetString($Bytes)}catch{Fail-AutoG16}
 $Roundtrip=$Utf8.GetBytes($Value)
 if($Roundtrip.Length-ne$Bytes.Length){Fail-AutoG16}
 for($Index=0;$Index-lt$Bytes.Length;$Index++){if($Roundtrip[$Index]-ne$Bytes[$Index]){Fail-AutoG16}}
 if($Value.IndexOf([char]0)-ge 0 -or $Value.IndexOf("`r")-ge 0){Fail-AutoG16}
 $Sq=[char]39;$Dq=[char]34
 return [string]$Sq+$Value.Replace([string]$Sq,[string]$Sq+$Dq+$Sq+$Dq+$Sq)+$Sq
}
function Quote-Crt([string]$Value) {
 if($Value.IndexOf([char]0)-ge 0){Fail-AutoG16}
 if($Value.Length-gt 0 -and $Value.IndexOfAny([char[]]@(' ',"`t",'"'))-lt 0){return $Value}
 $Result='"';$Slashes=0
 foreach($Character in $Value.ToCharArray()){
  if($Character-eq'\'){$Slashes++;continue}
  if($Character-eq'"'){$Result+=('\'*(2*$Slashes+1)-join'')+'"';$Slashes=0;continue}
  $Result+=('\'*$Slashes-join'')+$Character;$Slashes=0
 }
 return $Result+('\'*(2*$Slashes)-join'')+'"'
}
$ManifestBytes=Read-AutoG16 $ManifestPath $ManifestSize $ManifestSha256
$BootstrapBytes=Read-AutoG16 $BootstrapPath $BootstrapSize $BootstrapSha256
$ConfigBytes=Read-AutoG16 $ConfigPath $ConfigSize $ConfigSha256
$KnownHostsBytes=Read-AutoG16 $KnownHostsPath $KnownHostsSize $KnownHostsSha256
try{$Manifest=ConvertFrom-Json -InputObject $Utf8.GetString($ManifestBytes)}catch{Fail-AutoG16}
$Names=@($Manifest.trust_roots.PSObject.Properties.Name|Sort-Object)
$Expected=@('mac_scp','mac_ssh','rtwin_launcher','rtwin_remote_shell','rtwin_scp','rtwin_ssh','server_python','server_qstat','server_qsub','server_remote_shell')
if($Manifest.schema-ne'auto-g16-v3-transport-deployment-manifest/2' -or $Manifest.bootstrap_protocol-ne'auto-g16-v3-rtwin-bootstrap/2' -or ($Names-join',')-ne($Expected-join',')){Fail-AutoG16}
$RtwinSsh=$Manifest.trust_roots.rtwin_ssh
$RtwinScp=$Manifest.trust_roots.rtwin_scp
$BeforeSsh=Read-AutoG16 $RtwinSsh.path $RtwinSsh.expected_size_bytes $RtwinSsh.expected_sha256
$BeforeScp=Read-AutoG16 $RtwinScp.path $RtwinScp.expected_size_bytes $RtwinScp.expected_sha256
$ManifestBase64=[Convert]::ToBase64String($ManifestBytes)
$ServerPython=$Manifest.trust_roots.server_python.path
$ServerTokens=@($ServerPython,'-I','-S','-B','-c')
$QuotedServerTokens=@($ServerTokens|ForEach-Object{Quote-Posix $_})
$QuotedBootstrap=Quote-PosixFixedBootstrap $BootstrapBytes
$QuotedManifest=Quote-Posix $ManifestBase64
$ServerCommand=($QuotedServerTokens+@($QuotedBootstrap,$QuotedManifest))-join' '
$Arguments=@('-F',$ConfigPath,'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o',('UserKnownHostsFile='+$KnownHostsPath),'-o',('GlobalKnownHostsFile='+$KnownHostsPath),'-o','IdentityAgent=none','-o','PreferredAuthentications=publickey','-o','PubkeyAuthentication=yes','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no','-o','GSSAPIAuthentication=no','-o','HostbasedAuthentication=no','-o','VerifyHostKeyDNS=no','-o','UpdateHostKeys=no','-p',[string]$ServerPort,'-l',$ServerUser,'--',$ServerAlias,$ServerCommand)
$ArgumentLine=($Arguments|ForEach-Object{Quote-Crt $_})-join' '
if($ArgumentLine.Length-ge 30000){Fail-AutoG16}
$InnerBytes=$Utf8.GetBytes($ArgumentLine)
$InnerHasher=[Security.Cryptography.SHA256]::Create()
try{$InnerDigest=([BitConverter]::ToString($InnerHasher.ComputeHash($InnerBytes))).Replace('-','').ToLowerInvariant()}finally{$InnerHasher.Dispose()}
if($ArgumentLine.Length-ne$ExpectedInnerLength -or $InnerDigest-ne$ExpectedInnerSha256){Fail-AutoG16}
$OuterInput=[Console]::OpenStandardInput()
$FrameHeader=New-Object byte[] 12
Read-ExactAutoG16 $OuterInput $FrameHeader 0 12
if($FrameHeader[0]-ne 65 -or $FrameHeader[1]-ne 71 -or $FrameHeader[2]-ne 86 -or $FrameHeader[3]-ne 51){Fail-AutoG16}
[long]$PayloadLength=0
for($FrameIndex=4;$FrameIndex-lt 12;$FrameIndex++){
 if($PayloadLength-gt 700416){Fail-AutoG16}
 $PayloadLength=($PayloadLength*256)+[long]$FrameHeader[$FrameIndex]
}
if($PayloadLength-gt 179306484){Fail-AutoG16}
$RequestFrame=New-Object byte[] ([int](12+$PayloadLength))
[Array]::Copy($FrameHeader,0,$RequestFrame,0,12)
if($PayloadLength-gt 0){Read-ExactAutoG16 $OuterInput $RequestFrame 12 ([int]$PayloadLength)}
$Process=New-Object System.Diagnostics.Process
$Process.StartInfo.UseShellExecute=$false
$Process.StartInfo.FileName=$RtwinSsh.path
$Process.StartInfo.Arguments=$ArgumentLine
$Process.StartInfo.RedirectStandardInput=$true
$Process.StartInfo.RedirectStandardOutput=$true
$Process.StartInfo.RedirectStandardError=$true
if(-not $Process.Start()){Fail-AutoG16}
$Output=New-Object IO.MemoryStream
$ErrorOutput=New-Object IO.MemoryStream
$OutputBuffer=New-Object byte[] 65536
$ErrorBuffer=New-Object byte[] 65536
$OutputTask=$Process.StandardOutput.BaseStream.ReadAsync($OutputBuffer,0,$OutputBuffer.Length)
$ErrorTask=$Process.StandardError.BaseStream.ReadAsync($ErrorBuffer,0,$ErrorBuffer.Length)
$InputTask=$Process.StandardInput.BaseStream.WriteAsync($RequestFrame,0,$RequestFrame.Length)
$InputOpen=$true;$OutputOpen=$true;$ErrorOpen=$true
$ResponseExpected=[long]-1;$ResponseComplete=$false;$CompletionWatch=$null;$OwnedTeardown=$false
while($InputOpen -or $OutputOpen -or $ErrorOpen){
 $Pending=New-Object 'Collections.Generic.List[Threading.Tasks.Task]'
 if($InputOpen){$Pending.Add($InputTask)}
 if($OutputOpen){$Pending.Add($OutputTask)}
 if($ErrorOpen){$Pending.Add($ErrorTask)}
 if($ResponseComplete -and -not $OwnedTeardown -and -not $Process.HasExited){
  $CompletedIndex=[Threading.Tasks.Task]::WaitAny($Pending.ToArray(),100)
  if($CompletedIndex-lt 0){
   if($null-ne$CompletionWatch -and $CompletionWatch.ElapsedMilliseconds-ge 5000){
    try{if(-not $Process.HasExited){$Process.Kill();$OwnedTeardown=$true;$Process.WaitForExit()}}catch{
     try{$ExitedDuringKill=$Process.HasExited}catch{Fail-AutoG16}
     if(-not $ExitedDuringKill){Fail-AutoG16}
    }
   }
   continue
  }
 }else{$CompletedIndex=[Threading.Tasks.Task]::WaitAny($Pending.ToArray())}
 $Completed=$Pending[$CompletedIndex]
 if($InputOpen -and [Object]::ReferenceEquals($Completed,$InputTask)){
  try{$InputTask.GetAwaiter().GetResult();$Process.StandardInput.BaseStream.Flush();$Process.StandardInput.Close()}catch{try{$Process.Kill()}catch{};Fail-AutoG16}
  $InputOpen=$false
  if($ResponseComplete -and $null-eq$CompletionWatch){$CompletionWatch=[Diagnostics.Stopwatch]::StartNew()}
 }
 if($OutputOpen -and [Object]::ReferenceEquals($Completed,$OutputTask)){
  try{$Count=$OutputTask.GetAwaiter().GetResult()}catch{try{$Process.Kill()}catch{};Fail-AutoG16}
  if($Count-eq 0){$OutputOpen=$false}else{
   if($Output.Length+$Count-gt 179306496){try{$Process.Kill()}catch{};Fail-AutoG16}
   $Output.Write($OutputBuffer,0,$Count)
   if($ResponseExpected-lt 0 -and $Output.Length-ge 12){
    $ResponseBytes=$Output.GetBuffer()
    if($ResponseBytes[0]-ne 65 -or $ResponseBytes[1]-ne 71 -or $ResponseBytes[2]-ne 86 -or $ResponseBytes[3]-ne 51){try{$Process.Kill()}catch{};Fail-AutoG16}
    [long]$ResponsePayloadLength=0
    for($ResponseIndex=4;$ResponseIndex-lt 12;$ResponseIndex++){
     if($ResponsePayloadLength-gt 700416){try{$Process.Kill()}catch{};Fail-AutoG16}
     $ResponsePayloadLength=($ResponsePayloadLength*256)+[long]$ResponseBytes[$ResponseIndex]
    }
    if($ResponsePayloadLength-gt 179306484){try{$Process.Kill()}catch{};Fail-AutoG16}
    $ResponseExpected=[long](12+$ResponsePayloadLength)
   }
   if($ResponseExpected-ge 0 -and $Output.Length-gt$ResponseExpected){try{$Process.Kill()}catch{};Fail-AutoG16}
   if(-not $ResponseComplete -and $ResponseExpected-ge 0 -and $Output.Length-eq$ResponseExpected){
    $ResponseComplete=$true
    if(-not $InputOpen){$CompletionWatch=[Diagnostics.Stopwatch]::StartNew()}
   }
   $OutputTask=$Process.StandardOutput.BaseStream.ReadAsync($OutputBuffer,0,$OutputBuffer.Length)
  }
 }
 if($ErrorOpen -and [Object]::ReferenceEquals($Completed,$ErrorTask)){
  try{$Count=$ErrorTask.GetAwaiter().GetResult()}catch{try{$Process.Kill()}catch{};Fail-AutoG16}
  if($Count-eq 0){$ErrorOpen=$false}else{
   if($ErrorOutput.Length+$Count-gt 65536){try{$Process.Kill()}catch{};Fail-AutoG16}
   $ErrorOutput.Write($ErrorBuffer,0,$Count)
   $ErrorTask=$Process.StandardError.BaseStream.ReadAsync($ErrorBuffer,0,$ErrorBuffer.Length)
  }
 }
}
if(-not $ResponseComplete -or $Output.Length-ne$ResponseExpected -or $ErrorOutput.Length-ne 0){
 try{if(-not $Process.HasExited){$Process.Kill();$Process.WaitForExit()}}catch{}
 Fail-AutoG16
}
if(-not $Process.HasExited){
 $Remaining=5000
 if($null-ne$CompletionWatch){$Remaining=[Math]::Max(0,5000-[int]$CompletionWatch.ElapsedMilliseconds)}
 if(-not $Process.WaitForExit($Remaining)){$Process.Kill();$OwnedTeardown=$true;$Process.WaitForExit()}
}
$AfterSsh=Read-AutoG16 $RtwinSsh.path $RtwinSsh.expected_size_bytes $RtwinSsh.expected_sha256
$AfterScp=Read-AutoG16 $RtwinScp.path $RtwinScp.expected_size_bytes $RtwinScp.expected_sha256
$AfterManifest=Read-AutoG16 $ManifestPath $ManifestSize $ManifestSha256
$AfterBootstrap=Read-AutoG16 $BootstrapPath $BootstrapSize $BootstrapSha256
$AfterConfig=Read-AutoG16 $ConfigPath $ConfigSize $ConfigSha256
$AfterKnownHosts=Read-AutoG16 $KnownHostsPath $KnownHostsSize $KnownHostsSha256
$Output.Position=0;$Output.CopyTo([Console]::OpenStandardOutput())
$ErrorOutput.Position=0;$ErrorOutput.CopyTo([Console]::OpenStandardError())
if($OwnedTeardown){exit 0}
exit $Process.ExitCode
'''
_RTWIN_LAUNCHER_BYTES: Final = _RTWIN_LAUNCHER_SOURCE.encode("utf-8")
_RTWIN_LAUNCHER_SHA256: Final = "52ce86be68356832b5b357c1c088aee9fc1b19701fe98115ef97b2a077dd7f60"
_RTWIN_LAUNCHER_SIZE: Final = 11790
_RTWIN_LAUNCHER_LF_COUNT: Final = 200
if (
    len(_RTWIN_LAUNCHER_BYTES) != _RTWIN_LAUNCHER_SIZE
    or sha256(_RTWIN_LAUNCHER_BYTES).hexdigest() != _RTWIN_LAUNCHER_SHA256
    or _RTWIN_LAUNCHER_BYTES.count(b"\n") != _RTWIN_LAUNCHER_LF_COUNT
    or b"\r" in _RTWIN_LAUNCHER_BYTES
    or b"\x00" in _RTWIN_LAUNCHER_BYTES
    or not _RTWIN_LAUNCHER_BYTES.startswith(b"param(\n")
    or not _RTWIN_LAUNCHER_BYTES.endswith(b"exit $Process.ExitCode\n")
):
    raise RuntimeError("source-controlled RTwin launcher identity drifted")

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

def _posix_quote_exact_bootstrap_bytes_v2(source: bytes) -> str:
    if (
        type(source) is not bytes
        or len(source) != _BOOTSTRAP_SOURCE_SIZE
        or sha256(source).hexdigest() != _BOOTSTRAP_SOURCE_EXPECTED_SHA256
    ):
        raise TransportBoundaryError("fixed bootstrap source is invalid")
    try:
        decoded = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise TransportBoundaryError("fixed bootstrap source is invalid") from exc
    if decoded.encode("utf-8", errors="strict") != source or "\x00" in decoded or "\r" in decoded:
        raise TransportBoundaryError("fixed bootstrap source is invalid")
    return "'" + decoded.replace("'", "'\"'\"'") + "'"

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

def _ssh_effect_options(config:object,known_hosts:object)->list[str]:
    values=["-F",config.path]
    for option in (
        "BatchMode=yes","IdentitiesOnly=yes","StrictHostKeyChecking=yes",
        f"UserKnownHostsFile={known_hosts.path}",f"GlobalKnownHostsFile={known_hosts.path}",
        "IdentityAgent=none","PreferredAuthentications=publickey","PubkeyAuthentication=yes",
        "PasswordAuthentication=no","KbdInteractiveAuthentication=no","GSSAPIAuthentication=no",
        "HostbasedAuthentication=no","VerifyHostKeyDNS=no","UpdateHostKeys=no",
    ): values.extend(("-o",option))
    return values

_POWERSHELL_LOADER_TEMPLATE_V1: Final = (
    "$ErrorActionPreference='Stop';$p=@LAUNCHER_PATH@;$i=Get-Item -LiteralPath $p -Force;"
    "if($i.PSIsContainer -or (($i.Attributes -band [IO.FileAttributes]::ReparsePoint)-ne 0) -or $i.Length-ne@LAUNCHER_SIZE@){exit 97};"
    "$b=[IO.File]::ReadAllBytes($p);"
    "$a=([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($b))).Replace('-','').ToLowerInvariant();"
    "if($a-ne'@LAUNCHER_SHA@'){exit 97};"
    "$u=New-Object System.Text.UTF8Encoding($false,$true);$s=$u.GetString($b);$x=[ScriptBlock]::Create($s);"
    "&$x -ManifestPath @MANIFEST_PATH@ -ManifestSize @MANIFEST_SIZE@ -ManifestSha256 '@MANIFEST_SHA@'"
    " -BootstrapPath @BOOTSTRAP_PATH@ -BootstrapSize @BOOTSTRAP_SIZE@ -BootstrapSha256 '@BOOTSTRAP_SHA@'"
    " -ConfigPath @CONFIG_PATH@ -ConfigSize @CONFIG_SIZE@ -ConfigSha256 '@CONFIG_SHA@'"
    " -KnownHostsPath @KNOWN_PATH@ -KnownHostsSize @KNOWN_SIZE@ -KnownHostsSha256 '@KNOWN_SHA@'"
    " -ServerAlias @SERVER_ALIAS@ -ServerPort @SERVER_PORT@ -ServerUser @SERVER_USER@"
    " -ExpectedInnerLength @INNER_LENGTH@ -ExpectedInnerSha256 '@INNER_SHA@'"
)
_POWERSHELL_LOADER_TEMPLATE_V1_BYTES: Final = _POWERSHELL_LOADER_TEMPLATE_V1.encode("ascii")
_POWERSHELL_LOADER_TEMPLATE_V1_SIZE: Final = 1021
_POWERSHELL_LOADER_TEMPLATE_V1_SHA256: Final = "e9417a66f6597791c519c403dd709a9bd791d516e3c421a1eb79cb6dc9fd0a47"
if len(_POWERSHELL_LOADER_TEMPLATE_V1_BYTES)!=_POWERSHELL_LOADER_TEMPLATE_V1_SIZE or sha256(_POWERSHELL_LOADER_TEMPLATE_V1_BYTES).hexdigest()!=_POWERSHELL_LOADER_TEMPLATE_V1_SHA256:
    raise RuntimeError("source-controlled PowerShell loader template identity drifted")

def _render_inner_rtwin_arguments(authority:object,server:object)->str:
    roots=authority.manifest.trust_roots; effect=authority.ssh_effect
    manifest_arg=base64.b64encode(authority.manifest.raw_bytes).decode("ascii")
    server_tokens=(roots["server_python"].path,"-I","-S","-B","-c")
    server_command=" ".join((*(_posix_quote_v1(item) for item in server_tokens),_posix_quote_exact_bootstrap_bytes_v2(_BOOTSTRAP_SOURCE_BYTES),_posix_quote_v1(manifest_arg)))
    inner=[*_ssh_effect_options(effect.rtwin_to_server.config,effect.rtwin_to_server.known_hosts),"-p",str(server.port),"-l",server.user,"--",server.alias,server_command]
    arguments=" ".join(_crt_quote(item) for item in inner)
    if len(arguments)>=30000: raise TransportBoundaryError("RTwin inner command exceeds the closed boundary")
    return arguments

def _render_powershell_loader_v1(replacements:Mapping[str,str])->str:
    expected={"@LAUNCHER_PATH@","@LAUNCHER_SIZE@","@LAUNCHER_SHA@","@MANIFEST_PATH@","@MANIFEST_SIZE@","@MANIFEST_SHA@","@BOOTSTRAP_PATH@","@BOOTSTRAP_SIZE@","@BOOTSTRAP_SHA@","@CONFIG_PATH@","@CONFIG_SIZE@","@CONFIG_SHA@","@KNOWN_PATH@","@KNOWN_SIZE@","@KNOWN_SHA@","@SERVER_ALIAS@","@SERVER_PORT@","@SERVER_USER@","@INNER_LENGTH@","@INNER_SHA@"}
    if set(replacements)!=expected: raise TransportBoundaryError("PowerShell loader replacement inventory is invalid")
    rendered=_POWERSHELL_LOADER_TEMPLATE_V1
    for token in sorted(expected):
        value=replacements[token]
        if type(value) is not str or token in value or rendered.count(token)!=1: raise TransportBoundaryError("PowerShell loader replacement is invalid")
        rendered=rendered.replace(token,value)
    if "@" in rendered or '"' in rendered or any(character in rendered for character in "%!\r\n"):
        raise TransportBoundaryError("PowerShell loader is outside the closed CMD grammar")
    return rendered

def _build_rtwin_command(snapshot: object, authority: object) -> tuple[str, ...]:
    manifest=authority.manifest; roots=manifest.trust_roots; grammar=roots["rtwin_remote_shell"].shell_grammar
    profile=snapshot.resolved_server_profile
    if (
        authority.execution_snapshot_id!=snapshot.execution_snapshot_id
        or authority.resolved_server_profile_id!=profile.resolved_server_profile_id
        or authority.effective_config_sha256!=profile.effective_config_sha256
        or authority.bootstrap_source_sha256!=_BOOTSTRAP_SOURCE_SHA256
        or authority.bootstrap_source_size_bytes!=len(_BOOTSTRAP_SOURCE_BYTES)
        or manifest.sha256!=sha256(manifest.raw_bytes).hexdigest()
        or manifest.size_bytes!=len(manifest.raw_bytes)
    ): raise TransportBoundaryError("deployment authority differs from execution snapshot")
    if grammar!="cmd-powershell-launcher-v1": raise TransportBoundaryError("unsupported RTwin shell grammar")
    launcher=roots["rtwin_launcher"]
    if (
        launcher.expected_sha256!=_RTWIN_LAUNCHER_SHA256
        or launcher.expected_size_bytes!=_RTWIN_LAUNCHER_SIZE
    ): raise TransportBoundaryError("RTwin launcher differs from source-controlled bytes")
    effect=authority.ssh_effect; server=effect.rtwin_to_server.target
    def q(value:str)->str: return _powershell_quote_v1(value)
    inner_arguments=_render_inner_rtwin_arguments(authority,server)
    loader=_render_powershell_loader_v1({
        "@LAUNCHER_PATH@":q(launcher.path),"@LAUNCHER_SIZE@":str(launcher.expected_size_bytes),"@LAUNCHER_SHA@":str(launcher.expected_sha256),
        "@MANIFEST_PATH@":q(authority.manifest_path),"@MANIFEST_SIZE@":str(manifest.size_bytes),"@MANIFEST_SHA@":manifest.sha256,
        "@BOOTSTRAP_PATH@":q(authority.bootstrap_source_path),"@BOOTSTRAP_SIZE@":str(authority.bootstrap_source_size_bytes),"@BOOTSTRAP_SHA@":authority.bootstrap_source_sha256,
        "@CONFIG_PATH@":q(effect.rtwin_to_server.config.path),"@CONFIG_SIZE@":str(effect.rtwin_to_server.config.expected_size_bytes),"@CONFIG_SHA@":effect.rtwin_to_server.config.expected_sha256,
        "@KNOWN_PATH@":q(effect.rtwin_to_server.known_hosts.path),"@KNOWN_SIZE@":str(effect.rtwin_to_server.known_hosts.expected_size_bytes),"@KNOWN_SHA@":effect.rtwin_to_server.known_hosts.expected_sha256,
        "@SERVER_ALIAS@":q(server.alias),"@SERVER_PORT@":str(server.port),"@SERVER_USER@":q(server.user),
        "@INNER_LENGTH@":str(len(inner_arguments)),"@INNER_SHA@":sha256(inner_arguments.encode("utf-8")).hexdigest(),
    })
    remote_command=(
        f"{_cmd_quote_v1(roots['rtwin_remote_shell'].path)} -NoProfile -NonInteractive -Command \"{loader}\""
    )
    if len(remote_command)>=4096 or _BOOTSTRAP_SOURCE in remote_command or manifest.raw_bytes.decode("utf-8") in remote_command:
        raise TransportBoundaryError("RTwin outer command exceeds the closed boundary")
    mac=effect.mac_to_rtwin.target
    command=[roots["mac_ssh"].path,*_ssh_effect_options(effect.mac_to_rtwin.config,effect.mac_to_rtwin.known_hosts),"-p",str(mac.port),"-l",mac.user,"--",mac.alias,remote_command]
    return tuple(command)

__all__=["_BOOTSTRAP_PROTOCOL","_BOOTSTRAP_SOURCE","_BOOTSTRAP_SOURCE_BYTES","_BOOTSTRAP_SOURCE_NAME","_BOOTSTRAP_SOURCE_SHA256","_POWERSHELL_LOADER_TEMPLATE_V1","_POWERSHELL_LOADER_TEMPLATE_V1_SHA256","_POWERSHELL_LOADER_TEMPLATE_V1_SIZE","_RTWIN_LAUNCHER_BYTES","_RTWIN_LAUNCHER_LF_COUNT","_RTWIN_LAUNCHER_NAME","_RTWIN_LAUNCHER_SHA256","_RTWIN_LAUNCHER_SIZE","_RTWIN_LAUNCHER_SOURCE","_build_rtwin_command","_cmd_quote_v1","_crt_quote","_decode_response_frame","_encode_request_frame","_posix_quote_exact_bootstrap_bytes_v2","_posix_quote_v1","_powershell_quote_fixed_launcher_v1","_powershell_quote_v1","_render_inner_rtwin_arguments","_render_powershell_loader_v1"]
