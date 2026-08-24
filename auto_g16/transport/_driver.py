"""Exact deployment manifest, operation table, and bounded RTwin driver."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import os
from pathlib import PurePosixPath, PureWindowsPath
import re
import selectors
import signal
import stat
import subprocess
import time
from types import MappingProxyType
from typing import Final, Mapping, Protocol

from auto_g16.execution import ExecutionSnapshot, ServerProfile, assert_execution_snapshot_identity, resolve_server_profile

from ._bridge import _BOOTSTRAP_PROTOCOL, _BOOTSTRAP_SOURCE_BYTES, _BOOTSTRAP_SOURCE_NAME, _build_rtwin_command, _decode_response_frame, _encode_request_frame
from ._canonical import TransportBoundaryError, canonical_json_bytes, strict_canonical_json

_FIXED_ENV: Final = {"LANG":"C","LC_ALL":"C","PYTHONNOUSERSITE":"1","PYTHONUTF8":"1"}
_MANIFEST_NAME: Final = "transport-deployment-manifest-v1.json"
_MANIFEST_SCHEMA: Final = "auto-g16-v3-transport-deployment-manifest/1"
_RESOURCE_DESCRIPTOR_NAME: Final = "pbs-resource-enactment-v1.json"
_RESOURCE_DESCRIPTOR_SCHEMA: Final = "auto-g16-v3-pbs-resource-enactment/1"
_SYNTHETIC_RESOURCE_DIALECT: Final = "auto-g16-v3-pbs-resource-enactment/synthetic-test/1"
_TORQUE_RESOURCE_DIALECT: Final = "auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1"
_RESOURCE_DIALECTS: Final = MappingProxyType({_SYNTHETIC_RESOURCE_DIALECT:False,_TORQUE_RESOURCE_DIALECT:True})
_TORQUE_V30_A_QUEUE: Final = "batch"
_TORQUE_EXECUTABLES: Final = MappingProxyType({
    "server_qsub":("/usr/local/bin/qsub",418920,"f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d"),
    "server_qstat":("/usr/local/bin/qstat",185656,"3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a"),
})
_SSH_CONFIG_NAMES: Final = ("mac-ssh-config","mac-known-hosts","rtwin-ssh-config","rtwin-known-hosts")
_SSH_CONFIG_PATHS: Final = MappingProxyType({
    "mac-ssh-config":"mac_ssh_config_path","mac-known-hosts":"mac_known_hosts_path",
    "rtwin-ssh-config":"rtwin_ssh_config_path","rtwin-known-hosts":"rtwin_known_hosts_path",
})
_TABLE_NAME: Final = "auto-g16-rtwin-operation-table/2"
_TABLE_OBJECT: Final = {
    "version":_TABLE_NAME,"cwd_policy":"exact-remote-attempt-workspace","shell":False,"env":_FIXED_ENV,
    "limits":{"max_artifact_requests":4,"max_artifact_bytes":134217728,"max_capture_bytes":268435456},
    "operations":[
        {"name":"ALLOCATE_WORKSPACE","token":"allocate-workspace","argv_template":[],"timeout_seconds":30,"stdin_cap":65536,"stdout_cap":65536,"stderr_cap":65536},
        {"name":"STAGE_EXACT_FILE","token":"stage-exact-file","argv_template":["{logical_name}","{sha256}","{size_bytes}"],"timeout_seconds":900,"stdin_cap":179306496,"stdout_cap":65536,"stderr_cap":65536},
        {"name":"SUBMIT_QSUB_ONCE","token":"submit-qsub-once","argv_template":["{scheduler_dialect_id}","{cores}","{memory_mb}","{walltime_seconds}","{queue}","{pbs_basename}"],"timeout_seconds":30,"stdin_cap":65536,"stdout_cap":65536,"stderr_cap":65536},
        {"name":"QUERY_SCHEDULER","token":"query-scheduler","argv_template":["-f","{job_id}"],"timeout_seconds":30,"stdin_cap":65536,"stdout_cap":524288,"stderr_cap":65536},
        {"name":"STAT_EXACT_FILE","token":"stat-exact-file","argv_template":["{remote_relative_name}"],"timeout_seconds":30,"stdin_cap":65536,"stdout_cap":65536,"stderr_cap":65536},
        {"name":"FETCH_EXACT_FILE","token":"fetch-exact-file","argv_template":["{remote_relative_name}"],"timeout_seconds":900,"stdin_cap":65536,"stdout_cap":179306496,"stderr_cap":65536},
        {"name":"RECONCILE_SUBMISSION","token":"reconcile-submission","argv_template":[],"timeout_seconds":30,"stdin_cap":65536,"stdout_cap":262144,"stderr_cap":65536},
    ]}
_OPERATION_TABLE_BYTES: Final = canonical_json_bytes(_TABLE_OBJECT)
_OPERATION_TABLE_SHA256: Final = "14cdd511bb6c4eb78af8f07d774cfdae27fc1c661dae8692b45e48ccd7fa31af"
if len(_OPERATION_TABLE_BYTES)!=1570 or sha256(_OPERATION_TABLE_BYTES).hexdigest()!=_OPERATION_TABLE_SHA256: raise RuntimeError("source-controlled operation table drifted")

@dataclass(frozen=True,slots=True)
class _Operation:
    name:str; token:str; timeout_seconds:int; stdin_cap:int; stdout_cap:int; stderr_cap:int
_OPERATIONS: Final = {item["name"]:_Operation(item["name"],item["token"],item["timeout_seconds"],item["stdin_cap"],item["stdout_cap"],item["stderr_cap"]) for item in _TABLE_OBJECT["operations"]}

@dataclass(frozen=True,slots=True)
class _TrustRoot:
    name:str; attestation_mode:str; deployment_identity:str; expected_sha256:str|None; expected_size_bytes:int|None; path:str; platform:str; shell_grammar:str|None
@dataclass(frozen=True,slots=True)
class _DeploymentManifest:
    bootstrap_protocol:str; deployment_id:str; schema:str; trust_roots:Mapping[str,_TrustRoot]; raw_bytes:bytes; sha256:str; size_bytes:int
@dataclass(frozen=True,slots=True)
class _ResourceDialect:
    dialect_id:str; raw_bytes:bytes; sha256:str; size_bytes:int; live_capable:bool
@dataclass(frozen=True,slots=True)
class _ResourceEnactment:
    execution_snapshot_id:str; resolved_resource_request_id:str; cores:int; memory_mb:int; walltime_seconds:int; queue:str|None; scheduler_dialect_id:str
    def __post_init__(self)->None:
        for value,name in ((self.execution_snapshot_id,"execution snapshot"),(self.resolved_resource_request_id,"resource request"),(self.scheduler_dialect_id,"resource dialect")): _text(value,name)
        if any(type(value) is not int or value<1 for value in (self.cores,self.memory_mb,self.walltime_seconds)): raise TransportBoundaryError("resource enactment integer is invalid")
        if self.queue is not None and (not isinstance(self.queue,str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",self.queue) is None): raise TransportBoundaryError("resource enactment queue is invalid")
        if self.scheduler_dialect_id not in _RESOURCE_DIALECTS: raise TransportBoundaryError("resource dialect is not source-controlled")
    def payload(self)->dict[str,object]:
        return {"execution_snapshot_id":self.execution_snapshot_id,"resolved_resource_request_id":self.resolved_resource_request_id,"cores":self.cores,"memory_mb":self.memory_mb,"walltime_seconds":self.walltime_seconds,"queue":self.queue,"scheduler_dialect_id":self.scheduler_dialect_id}
@dataclass(frozen=True,slots=True)
class _BoundEffectFile:
    name:str; path:str; platform:str; expected_sha256:str; expected_size_bytes:int
@dataclass(frozen=True,slots=True)
class _SSHConfigTarget:
    alias:str; host:str; port:int; user:str; identity_file:str=field(repr=False)
@dataclass(frozen=True,slots=True)
class _SSHConfigHop:
    config:_BoundEffectFile; known_hosts:_BoundEffectFile; target:_SSHConfigTarget
@dataclass(frozen=True,slots=True)
class _SSHEffectAuthority:
    mac_to_rtwin:_SSHConfigHop; rtwin_to_server:_SSHConfigHop
@dataclass(frozen=True,slots=True)
class _DeploymentAuthority:
    manifest:_DeploymentManifest; resource_dialect:_ResourceDialect; ssh_effect:_SSHEffectAuthority; resolved_server_profile_id:str; effective_config_sha256:str; execution_snapshot_id:str; bootstrap_source_sha256:str; bootstrap_source_size_bytes:int
@dataclass(frozen=True,slots=True,kw_only=True)
class _Invocation:
    operation:_Operation; argv:tuple[str,...]; cwd:str; request:Mapping[str,object]; authority:_DeploymentAuthority
@dataclass(frozen=True,slots=True,kw_only=True)
class _TextResult:
    stdout:bytes; stderr:bytes; returncode:int|None; eof_stdout:bool; eof_stderr:bool; completion_status:str
    def __post_init__(self)->None:
        if type(self.stdout) is not bytes or type(self.stderr) is not bytes or type(self.eof_stdout) is not bool or type(self.eof_stderr) is not bool: raise TransportBoundaryError("text result types are invalid")
        if self.returncode is not None and (type(self.returncode) is not int): raise TransportBoundaryError("returncode is invalid")
        if self.completion_status not in {"completed","timeout","transport-error"}: raise TransportBoundaryError("completion status is invalid")
@dataclass(frozen=True,slots=True,kw_only=True)
class _FetchResult:
    status:str; content:bytes=b""; before_identity:str|None=None; after_identity:str|None=None; before_size:int|None=None; after_size:int|None=None; before_sha256:str|None=None; after_sha256:str|None=None
    def __post_init__(self)->None:
        if self.status not in {"found","missing","unstable","transport-error"} or type(self.content) is not bytes: raise TransportBoundaryError("fetch result types are invalid")
        values=(self.before_identity,self.after_identity,self.before_size,self.after_size,self.before_sha256,self.after_sha256)
        if self.status=="found":
            if any(value is None for value in values) or type(self.before_identity) is not str or type(self.after_identity) is not str or type(self.before_size) is not int or type(self.after_size) is not int or type(self.before_sha256) is not str or type(self.after_sha256) is not str: raise TransportBoundaryError("found fetch result is incomplete")
        elif self.content or any(value is not None for value in values): raise TransportBoundaryError("non-found fetch result carries authority")

class _RTWinDriver(Protocol):
    def invoke_text(self,snapshot:ExecutionSnapshot,invocation:_Invocation)->_TextResult:...
    def invoke_fetch(self,snapshot:ExecutionSnapshot,invocation:_Invocation)->_FetchResult:...

_ROOT_RULES: Final = {
    "mac_ssh":("macos","controller-file-v1",True,None),"mac_scp":("macos","controller-file-v1",True,None),
    "rtwin_ssh":("windows","rtwin-shell-file-v1",True,None),"rtwin_scp":("windows","rtwin-shell-file-v1",True,None),
    "rtwin_remote_shell":("windows","deployment-root-v1",False,{"powershell-v1","cmd-v1"}),"server_remote_shell":("posix","deployment-root-v1",False,{"posix-sh-v1"}),
    "server_python":("posix","server-self-check-v1",True,None),"server_qsub":("posix","server-python-file-v1",True,None),"server_qstat":("posix","server-python-file-v1",True,None)}
_ROOT_KEYS: Final = {"attestation_mode","deployment_identity","expected_sha256","expected_size_bytes","path","platform","shell_grammar"}

def _text(value:object,name:str)->str:
    if not isinstance(value,str) or not value or value!=value.strip() or any(c in value for c in "\x00\r\n"): raise TransportBoundaryError(f"manifest {name} is invalid")
    return value
def _parse_deployment_manifest(raw:bytes)->_DeploymentManifest:
    value=strict_canonical_json(raw,"deployment manifest")
    if not isinstance(value,dict) or set(value)!={"bootstrap_protocol","deployment_id","schema","trust_roots"} or value["schema"]!=_MANIFEST_SCHEMA or value["bootstrap_protocol"]!=_BOOTSTRAP_PROTOCOL: raise TransportBoundaryError("manifest top-level shape/version is invalid")
    roots_raw=value["trust_roots"]
    if not isinstance(roots_raw,dict) or set(roots_raw)!=set(_ROOT_RULES): raise TransportBoundaryError("manifest root inventory is invalid")
    roots={}
    for name,(platform,mode,required,grammars) in _ROOT_RULES.items():
        item=roots_raw[name]
        if not isinstance(item,dict) or set(item)!=_ROOT_KEYS or item["platform"]!=platform or item["attestation_mode"]!=mode: raise TransportBoundaryError(f"manifest root {name} shape is invalid")
        path=_text(item["path"],f"{name}.path"); parsed=PureWindowsPath(path) if platform=="windows" else PurePosixPath(path)
        if not parsed.is_absolute() or any(part in {".",".."} for part in parsed.parts): raise TransportBoundaryError(f"manifest root {name} path is invalid")
        digest,size,grammar=item["expected_sha256"],item["expected_size_bytes"],item["shell_grammar"]
        if required and (not isinstance(digest,str) or re.fullmatch(r"[0-9a-f]{64}",digest) is None or type(size) is not int or size<1 or grammar is not None): raise TransportBoundaryError(f"manifest root {name} identity is invalid")
        if not required and (digest is not None or size is not None or not isinstance(grammar,str) or grammar not in grammars): raise TransportBoundaryError(f"manifest root {name} grammar is invalid")
        roots[name]=_TrustRoot(name,mode,_text(item["deployment_identity"],f"{name}.deployment_identity"),digest,size,path,platform,grammar)
    return _DeploymentManifest(_BOOTSTRAP_PROTOCOL,_text(value["deployment_id"],"deployment_id"),_MANIFEST_SCHEMA,MappingProxyType(roots),raw,sha256(raw).hexdigest(),len(raw))

def _parse_resource_descriptor(raw:bytes)->_ResourceDialect:
    value=strict_canonical_json(raw,"resource enactment descriptor")
    if not isinstance(value,dict) or set(value)!={"schema","dialect"} or value.get("schema")!=_RESOURCE_DESCRIPTOR_SCHEMA:
        raise TransportBoundaryError("resource enactment descriptor shape/version is invalid")
    dialect=_text(value.get("dialect"),"resource dialect")
    if dialect not in _RESOURCE_DIALECTS:
        raise TransportBoundaryError("resource dialect is not source-controlled")
    return _ResourceDialect(dialect,raw,sha256(raw).hexdigest(),len(raw),_RESOURCE_DIALECTS[dialect])

def _resource_enactment(snapshot:ExecutionSnapshot,authority:_DeploymentAuthority)->_ResourceEnactment:
    if authority.execution_snapshot_id!=snapshot.execution_snapshot_id: raise TransportBoundaryError("resource authority belongs to another snapshot")
    request=snapshot.resolved_resource_request
    values=(request.cores,request.memory_mb,request.walltime_seconds)
    if any(type(value) is not int or value<1 for value in values): raise TransportBoundaryError("snapshot resource value is invalid")
    queue=request.queue
    if queue is not None and (not isinstance(queue,str) or not queue or queue!=queue.strip() or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",queue) is None): raise TransportBoundaryError("snapshot queue is invalid")
    return _ResourceEnactment(snapshot.execution_snapshot_id,request.resolved_resource_request_id,request.cores,request.memory_mb,request.walltime_seconds,queue,authority.resource_dialect.dialect_id)

def _render_qsub_argv(enactment:_ResourceEnactment,pbs_basename:str)->tuple[str,...]:
    if not isinstance(enactment,_ResourceEnactment) or not isinstance(pbs_basename,str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",pbs_basename) is None: raise TransportBoundaryError("qsub render input is invalid")
    if enactment.scheduler_dialect_id==_SYNTHETIC_RESOURCE_DIALECT:
        argv=["--auto-g16-synthetic-cores",str(enactment.cores),"--auto-g16-synthetic-memory-mb",str(enactment.memory_mb),"--auto-g16-synthetic-walltime-seconds",str(enactment.walltime_seconds)]
        if enactment.queue is not None: argv.extend(["--auto-g16-synthetic-queue",enactment.queue])
        argv.append(pbs_basename); return tuple(argv)
    if enactment.scheduler_dialect_id==_TORQUE_RESOURCE_DIALECT:
        if enactment.queue!=_TORQUE_V30_A_QUEUE: raise TransportBoundaryError("Torque V30-A queue must be exact")
        resources=f"nodes=1:ppn={enactment.cores},mem={enactment.memory_mb}mb,walltime={enactment.walltime_seconds}"
        return ("-l",resources,"-q",_TORQUE_V30_A_QUEUE,pbs_basename)
    raise TransportBoundaryError("resource dialect is not source-controlled")

def _validate_resource_deployment(manifest:_DeploymentManifest,dialect:_ResourceDialect)->None:
    if dialect.dialect_id==_SYNTHETIC_RESOURCE_DIALECT: return
    if dialect.dialect_id!=_TORQUE_RESOURCE_DIALECT: raise TransportBoundaryError("resource dialect is not source-controlled")
    for name,expected in _TORQUE_EXECUTABLES.items():
        root=manifest.trust_roots[name]
        if (root.path,root.expected_size_bytes,root.expected_sha256)!=expected: raise TransportBoundaryError(f"Torque {name} identity differs from deployment evidence")

def _freeze_profile(profile:ServerProfile)->ServerProfile:
    if not isinstance(profile,ServerProfile): raise TransportBoundaryError("current profile is invalid")
    try:
        return ServerProfile(
            server_profile_id=profile.server_profile_id,profile_revision=profile.profile_revision,
            transport_kind=profile.transport_kind,target_host=profile.target_host,target_port=profile.target_port,
            remote_user=profile.remote_user,jump_topology=list(profile.jump_topology),
            host_key_policy=profile.host_key_policy,batch_mode=profile.batch_mode,identities_only=profile.identities_only,
            remote_root=profile.remote_root,platform_paths=dict(profile.platform_paths),
            config_files=list(profile.config_files),runtime_contents=dict(profile.runtime_contents),
        )
    except (RuntimeError,TypeError,ValueError) as exc: raise TransportBoundaryError("current profile cannot be frozen") from exc

def _closed_effect_path(value:object,platform:str,name:str)->str:
    path=_text(value,name)
    if any(character in path for character in "%$~*?[]{}"): raise TransportBoundaryError(f"{name} contains path expansion syntax")
    parsed=PureWindowsPath(path) if platform=="windows" else PurePosixPath(path)
    if not parsed.is_absolute() or any(part in {".",".."} for part in parsed.parts): raise TransportBoundaryError(f"{name} is not an absolute closed path")
    return path

def _parse_ssh_config(raw:bytes,*,platform:str,config_name:str,config_path:str,known_hosts_path:str)->tuple[_BoundEffectFile,_SSHConfigTarget]:
    if type(raw) is not bytes or not raw or raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw or b"\r" in raw or b"\t" in raw or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise TransportBoundaryError(f"{config_name} byte grammar is invalid")
    try: text=raw.decode("utf-8",errors="strict")
    except UnicodeDecodeError as exc: raise TransportBoundaryError(f"{config_name} is not strict UTF-8") from exc
    directives:dict[str,str]={}
    semantic_index=0
    for line in text[:-1].split("\n"):
        if not line or line.startswith("#"): continue
        match=re.fullmatch(r" *([A-Za-z][A-Za-z0-9]*) ([^ ]+)",line)
        if match is None: raise TransportBoundaryError(f"{config_name} line grammar is invalid")
        key,value=match.groups(); semantic_index+=1
        if semantic_index==1 and key!="Host": raise TransportBoundaryError(f"{config_name} first semantic line is not Host")
        if key not in {"Host","HostName","Port","User","IdentityFile","IdentitiesOnly","StrictHostKeyChecking","UserKnownHostsFile"} or key in directives:
            raise TransportBoundaryError(f"{config_name} directive inventory is invalid")
        directives[key]=value
    required={"Host","HostName","User","IdentityFile","IdentitiesOnly","StrictHostKeyChecking","UserKnownHostsFile"}
    if set(directives) not in (required,required|{"Port"}) or directives["IdentitiesOnly"]!="yes" or directives["StrictHostKeyChecking"]!="yes":
        raise TransportBoundaryError(f"{config_name} required directives are invalid")
    alias,host,user=directives["Host"],directives["HostName"],directives["User"]
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",alias) is None or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*",host) is None or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",user) is None:
        raise TransportBoundaryError(f"{config_name} target grammar is invalid")
    port_text=directives.get("Port","22")
    if re.fullmatch(r"[1-9][0-9]{0,4}",port_text) is None or int(port_text)>65535: raise TransportBoundaryError(f"{config_name} port is invalid")
    identity=_closed_effect_path(directives["IdentityFile"],platform,f"{config_name}.IdentityFile")
    if _closed_effect_path(directives["UserKnownHostsFile"],platform,f"{config_name}.UserKnownHostsFile")!=known_hosts_path:
        raise TransportBoundaryError(f"{config_name} known-host path differs from profile")
    bound=_BoundEffectFile(config_name,config_path,platform,sha256(raw).hexdigest(),len(raw))
    return bound,_SSHConfigTarget(alias,host,int(port_text),user,identity)

def _resolve_ssh_effect(profile:ServerProfile,current:object)->_SSHEffectAuthority:
    if set(name for name,_content in profile.config_files)!=set(_SSH_CONFIG_NAMES) or len(profile.config_files)!=len(_SSH_CONFIG_NAMES):
        raise TransportBoundaryError("SSH effect config inventory is invalid")
    contents=dict(profile.config_files); paths=getattr(current,"platform_paths")
    bound:dict[str,_BoundEffectFile]={}
    for logical_name,path_key in _SSH_CONFIG_PATHS.items():
        platform="macos" if logical_name.startswith("mac-") else "windows"
        try: path_value=paths[path_key]
        except KeyError as exc: raise TransportBoundaryError("SSH effect path inventory is incomplete") from exc
        path=_closed_effect_path(path_value,platform,path_key)
        raw=contents[logical_name]
        if logical_name.endswith("known-hosts"):
            if type(raw) is not bytes or not raw: raise TransportBoundaryError(f"{logical_name} bytes are invalid")
            bound[logical_name]=_BoundEffectFile(logical_name,path,platform,sha256(raw).hexdigest(),len(raw))
    mac_config,mac_target=_parse_ssh_config(contents["mac-ssh-config"],platform="macos",config_name="mac-ssh-config",config_path=_closed_effect_path(paths["mac_ssh_config_path"],"macos","mac_ssh_config_path"),known_hosts_path=bound["mac-known-hosts"].path)
    rtwin_config,server_target=_parse_ssh_config(contents["rtwin-ssh-config"],platform="windows",config_name="rtwin-ssh-config",config_path=_closed_effect_path(paths["rtwin_ssh_config_path"],"windows","rtwin_ssh_config_path"),known_hosts_path=bound["rtwin-known-hosts"].path)
    target=getattr(current,"target_identity"); jumps=target["jump_topology"]
    if len(jumps)!=1: raise TransportBoundaryError("exactly one RTwin hop is required")
    rtwin=jumps[0]
    if (mac_target.host,mac_target.port,mac_target.user)!=(rtwin["host"],rtwin["port"],rtwin["user"]): raise TransportBoundaryError("Mac SSH config target differs from RTwin hop")
    if (server_target.host,server_target.port,server_target.user)!=(target["destination_host"],target["destination_port"],getattr(current,"remote_user")): raise TransportBoundaryError("RTwin SSH config target differs from server target")
    return _SSHEffectAuthority(_SSHConfigHop(mac_config,bound["mac-known-hosts"],mac_target),_SSHConfigHop(rtwin_config,bound["rtwin-known-hosts"],server_target))

def _resolve_deployment_authority(snapshot:ExecutionSnapshot,current_profile:ServerProfile)->_DeploymentAuthority:
    try:
        assert_execution_snapshot_identity(snapshot); frozen_profile=_freeze_profile(current_profile); current=resolve_server_profile(frozen_profile)
    except Exception as exc: raise TransportBoundaryError("current profile cannot be resolved") from exc
    if _freeze_profile(current_profile)!=frozen_profile: raise TransportBoundaryError("current profile mutated during Transport resolution")
    frozen=snapshot.resolved_server_profile
    if current!=frozen or current.semantic_payload()!=frozen.semantic_payload() or current.resolved_server_profile_id!=frozen.resolved_server_profile_id or current.effective_config_sha256!=frozen.effective_config_sha256: raise TransportBoundaryError("current profile differs from snapshot")
    try: raw=frozen_profile.runtime_contents[_MANIFEST_NAME]; descriptor_raw=frozen_profile.runtime_contents[_RESOURCE_DESCRIPTOR_NAME]; manifest_identity=frozen.runtime_identities[_MANIFEST_NAME]; descriptor_identity=frozen.runtime_identities[_RESOURCE_DESCRIPTOR_NAME]; table_identity=frozen.runtime_identities[_TABLE_NAME]; source_identity=frozen.runtime_identities[_BOOTSTRAP_SOURCE_NAME]
    except KeyError as exc: raise TransportBoundaryError("required Transport runtime content is missing") from exc
    if manifest_identity!={"sha256":sha256(raw).hexdigest(),"size_bytes":len(raw)}: raise TransportBoundaryError("manifest differs from snapshot")
    if descriptor_identity!={"sha256":sha256(descriptor_raw).hexdigest(),"size_bytes":len(descriptor_raw)}: raise TransportBoundaryError("resource descriptor differs from snapshot")
    if table_identity!={"sha256":_OPERATION_TABLE_SHA256,"size_bytes":1570}: raise TransportBoundaryError("operation table differs from source")
    expected_source={"sha256":sha256(_BOOTSTRAP_SOURCE_BYTES).hexdigest(),"size_bytes":len(_BOOTSTRAP_SOURCE_BYTES)}
    if source_identity!=expected_source: raise TransportBoundaryError("bootstrap source differs from source")
    manifest=_parse_deployment_manifest(raw); dialect=_parse_resource_descriptor(descriptor_raw); _validate_resource_deployment(manifest,dialect); ssh_effect=_resolve_ssh_effect(frozen_profile,current)
    return _DeploymentAuthority(manifest,dialect,ssh_effect,frozen.resolved_server_profile_id,frozen.effective_config_sha256,snapshot.execution_snapshot_id,expected_source["sha256"],expected_source["size_bytes"])

def _attest_local(root:_TrustRoot)->tuple[int,int]:
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    try: fd=os.open(root.path,flags)
    except OSError as exc: raise TransportBoundaryError(f"{root.name} is unavailable") from exc
    try:
        opened=os.fstat(fd); named=os.stat(root.path,follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode) or opened.st_mode&0o111==0 or (opened.st_dev,opened.st_ino)!=(named.st_dev,named.st_ino) or opened.st_size!=root.expected_size_bytes: raise TransportBoundaryError(f"{root.name} identity drifted")
        digest=sha256(); remaining=opened.st_size
        while remaining:
            chunk=os.read(fd,min(65536,remaining))
            if not chunk: raise TransportBoundaryError(f"{root.name} read was short")
            digest.update(chunk); remaining-=len(chunk)
        if os.read(fd,1) or digest.hexdigest()!=root.expected_sha256: raise TransportBoundaryError(f"{root.name} bytes drifted")
        return opened.st_dev,opened.st_ino
    finally: os.close(fd)

def _attest_local_effect_file(bound:_BoundEffectFile)->tuple[int,int]:
    if bound.platform!="macos": raise TransportBoundaryError(f"{bound.name} is not controller-local")
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    try: fd=os.open(bound.path,flags)
    except OSError as exc: raise TransportBoundaryError(f"{bound.name} is unavailable") from exc
    try:
        opened=os.fstat(fd); named=os.stat(bound.path,follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode) or (opened.st_dev,opened.st_ino)!=(named.st_dev,named.st_ino) or opened.st_size!=bound.expected_size_bytes: raise TransportBoundaryError(f"{bound.name} identity drifted")
        digest=sha256(); remaining=opened.st_size
        while remaining:
            chunk=os.read(fd,min(65536,remaining))
            if not chunk: raise TransportBoundaryError(f"{bound.name} read was short")
            digest.update(chunk); remaining-=len(chunk)
        if os.read(fd,1) or digest.hexdigest()!=bound.expected_sha256: raise TransportBoundaryError(f"{bound.name} bytes drifted")
        return opened.st_dev,opened.st_ino
    finally: os.close(fd)

def _canonical_b64(value:object)->bytes:
    import base64
    if type(value) is not str: raise TransportBoundaryError("response base64 is invalid")
    try: raw=base64.b64decode(value.encode("ascii"),validate=True)
    except Exception as exc: raise TransportBoundaryError("response base64 is invalid") from exc
    if base64.b64encode(raw).decode("ascii")!=value: raise TransportBoundaryError("response base64 is noncanonical")
    return raw

def _validate_result(operation:str,result:Mapping[str,object])->None:
    keys=set(result)
    if operation=="ALLOCATE_WORKSPACE": expected={"remote_workspace","workspace_physical_token_base64"}
    elif operation=="STAGE_EXACT_FILE": expected={"artifact_kind","logical_name","remote_relative_name","sha256","size_bytes","artifact_physical_token_base64"}
    elif operation=="SUBMIT_QSUB_ONCE": expected={"job_id"}
    elif operation=="QUERY_SCHEDULER": expected={"stdout_base64","stderr_base64","returncode","eof_stdout","eof_stderr","completion_status"}
    elif operation=="STAT_EXACT_FILE":
        expected={"presence","remote_relative_name"} if result.get("presence")=="absent" else {"presence","remote_relative_name","size_bytes","file_physical_token_base64"}
    elif operation=="FETCH_EXACT_FILE": expected={"remote_relative_name","size_bytes","sha256","content_base64","file_physical_token_base64","eof"}
    elif operation=="RECONCILE_SUBMISSION": expected={"effect_state","job_id"} if result.get("effect_state")=="confirmed_effect" else {"effect_state"}
    else: raise TransportBoundaryError("unknown response operation")
    if keys!=expected: raise TransportBoundaryError("response result shape is invalid")
    for key in keys:
        value=result[key]
        if key.endswith("_base64"):
            decoded=_canonical_b64(value)
            if "token" in key and not 1<=len(decoded)<=4096: raise TransportBoundaryError("response token size is invalid")
        elif key.endswith("_bytes") or key=="returncode":
            if type(value) is not int or value<0 and key.endswith("_bytes"): raise TransportBoundaryError("response integer is invalid")
        elif key in {"eof","eof_stdout","eof_stderr"}:
            if value is not True: raise TransportBoundaryError("response EOF is invalid")
        elif type(value) is not str or not value or any(c in value for c in "\x00\r\n"):
            raise TransportBoundaryError("response string is invalid")
    if operation=="QUERY_SCHEDULER" and result["completion_status"]!="completed": raise TransportBoundaryError("qstat response completion is invalid")
    if operation=="RECONCILE_SUBMISSION" and result["effect_state"] not in {"confirmed_effect","confirmed_no_effect","possibly_effectful"}: raise TransportBoundaryError("reconciliation state is invalid")

class _SubprocessRTWinDriver:
    """Live-capable exact bridge; construction and offline tests make no call."""
    @staticmethod
    def _kill(process:subprocess.Popen[bytes])->None:
        try: os.killpg(process.pid,signal.SIGKILL)
        except OSError:
            try: process.kill()
            except OSError: pass

    def _communicate_bounded(self,process:subprocess.Popen[bytes],request:bytes,operation:_Operation)->tuple[bytes,bytes,int|None,str,bool,bool]:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            self._kill(process); process.wait(); return b"",b"",None,"transport-error",False,False
        streams={"stdin":process.stdin,"stdout":process.stdout,"stderr":process.stderr}
        selector=selectors.DefaultSelector(); output={"stdout":bytearray(),"stderr":bytearray()}; offset=0
        try:
            for stream in streams.values(): os.set_blocking(stream.fileno(),False)
            selector.register(process.stdin,selectors.EVENT_WRITE,"stdin")
            selector.register(process.stdout,selectors.EVENT_READ,"stdout")
            selector.register(process.stderr,selectors.EVENT_READ,"stderr")
            deadline=time.monotonic()+operation.timeout_seconds
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    self._kill(process); process.wait(); return b"",b"",None,"timeout",False,False
                events=selector.select(remaining)
                if not events:
                    self._kill(process); process.wait(); return b"",b"",None,"timeout",False,False
                for key,_mask in events:
                    name=key.data; stream=key.fileobj
                    if name=="stdin":
                        try: written=os.write(stream.fileno(),request[offset:offset+65536])
                        except BrokenPipeError: written=0
                        offset+=written
                        if offset==len(request) or written==0:
                            selector.unregister(stream); stream.close()
                        continue
                    cap=operation.stdout_cap if name=="stdout" else operation.stderr_cap
                    chunk=os.read(stream.fileno(),min(65536,cap+1-len(output[name])))
                    if not chunk:
                        selector.unregister(stream); stream.close(); continue
                    output[name].extend(chunk)
                    if len(output[name])>cap:
                        self._kill(process); process.wait(); return b"",b"",None,"transport-error",False,False
            remaining=max(0.0,deadline-time.monotonic())
            try: returncode=process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                self._kill(process); process.wait(); return b"",b"",None,"timeout",False,False
            return bytes(output["stdout"]),bytes(output["stderr"]),returncode,"completed",True,True
        except (OSError,ValueError):
            self._kill(process); process.wait(); return b"",b"",None,"transport-error",False,False
        finally:
            selector.close()
            for stream in streams.values():
                try: stream.close()
                except OSError: pass
    def _run(self,snapshot:ExecutionSnapshot,invocation:_Invocation)->tuple[bytes,bytes,int|None,str,bool,bool]:
        if not invocation.authority.resource_dialect.live_capable:
            return b"",b"",None,"transport-error",False,False
        roots=invocation.authority.manifest.trust_roots
        local_files=(invocation.authority.ssh_effect.mac_to_rtwin.config,invocation.authority.ssh_effect.mac_to_rtwin.known_hosts)
        before={name:_attest_local(roots[name]) for name in ("mac_ssh","mac_scp")}
        before.update({bound.name:_attest_local_effect_file(bound) for bound in local_files})
        request=_encode_request_frame(invocation.request,cap=invocation.operation.stdin_cap)
        command=_build_rtwin_command(snapshot,invocation.authority)
        process=None
        try:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(_FIXED_ENV),shell=False,start_new_session=True)
            stdout,stderr,returncode,status,eofout,eoferr=self._communicate_bounded(process,request,invocation.operation)
            after={name:_attest_local(roots[name]) for name in ("mac_ssh","mac_scp")}
            after.update({bound.name:_attest_local_effect_file(bound) for bound in local_files})
            if before!=after: return b"",b"",None,"transport-error",False,False
            if status!="completed": return stdout,stderr,returncode,status,eofout,eoferr
            return stdout,stderr,returncode,"completed",True,True
        except (OSError,TransportBoundaryError):
            if process is not None:
                try: active=process.poll() is None
                except (AttributeError,OSError): active=True
                if active: self._kill(process)
            return b"",b"",None,"transport-error",False,False
    def invoke_text(self,snapshot:ExecutionSnapshot,invocation:_Invocation)->_TextResult:
        stdout,stderr,code,status,eofout,eoferr=self._run(snapshot,invocation)
        if status!="completed" or code!=0 or stderr: return _TextResult(stdout=b"",stderr=b"",returncode=code,eof_stdout=eofout,eof_stderr=eoferr,completion_status=status)
        try: result=_decode_response_frame(stdout,operation=invocation.operation.name,cap=invocation.operation.stdout_cap)
        except TransportBoundaryError: return _TextResult(stdout=b"",stderr=b"",returncode=None,eof_stdout=eofout,eof_stderr=eoferr,completion_status="transport-error")
        try: _validate_result(invocation.operation.name,result)
        except TransportBoundaryError: return _TextResult(stdout=b"",stderr=b"",returncode=None,eof_stdout=False,eof_stderr=False,completion_status="transport-error")
        if invocation.operation.name=="QUERY_SCHEDULER":
            out=_canonical_b64(result["stdout_base64"]); err=_canonical_b64(result["stderr_base64"])
            if len(out)>262144 or len(err)>65536: return _TextResult(stdout=b"",stderr=b"",returncode=None,eof_stdout=False,eof_stderr=False,completion_status="transport-error")
            return _TextResult(stdout=out,stderr=err,returncode=result.get("returncode"),eof_stdout=result.get("eof_stdout") is True,eof_stderr=result.get("eof_stderr") is True,completion_status=result.get("completion_status","transport-error"))
        return _TextResult(stdout=canonical_json_bytes(result),stderr=b"",returncode=0,eof_stdout=True,eof_stderr=True,completion_status="completed")
    def invoke_fetch(self,snapshot:ExecutionSnapshot,invocation:_Invocation)->_FetchResult:
        stdout,stderr,code,status,eofout,eoferr=self._run(snapshot,invocation)
        if status!="completed" or code!=0 or stderr or not eofout or not eoferr: return _FetchResult(status="transport-error")
        try:
            result=_decode_response_frame(stdout,operation=invocation.operation.name,cap=invocation.operation.stdout_cap); _validate_result(invocation.operation.name,result); content=_canonical_b64(result["content_base64"]); token=result["file_physical_token_base64"]
            payload=invocation.request["payload"]
            if not isinstance(payload,Mapping): raise ValueError
            if result["remote_relative_name"]!=payload.get("remote_relative_name") or result["size_bytes"]!=payload.get("expected_size_bytes") or token!=payload.get("expected_file_physical_token_base64"): raise ValueError
            if result["size_bytes"]!=len(content) or result["sha256"]!=sha256(content).hexdigest(): raise ValueError
            return _FetchResult(status="found",content=content,before_identity=token,after_identity=token,before_size=len(content),after_size=len(content),before_sha256=result["sha256"],after_sha256=result["sha256"])
        except Exception: return _FetchResult(status="unstable")

def _operation(name:str)->_Operation:
    aliases={"allocate":"ALLOCATE_WORKSPACE","stage":"STAGE_EXACT_FILE","qsub":"SUBMIT_QSUB_ONCE","qstat":"QUERY_SCHEDULER","stat":"STAT_EXACT_FILE","fetch":"FETCH_EXACT_FILE","reconcile":"RECONCILE_SUBMISSION"}
    try: return _OPERATIONS[aliases.get(name,name)]
    except KeyError as exc: raise TransportBoundaryError("operation is outside the frozen table") from exc

def _is_text_result_closed(value:object)->bool:
    return isinstance(value,_TextResult) and type(value.stdout) is bytes and type(value.stderr) is bytes and (value.returncode is None or type(value.returncode) is int) and type(value.eof_stdout) is bool and type(value.eof_stderr) is bool and value.completion_status in {"completed","timeout","transport-error"}
def _is_fetch_result_closed(value:object)->bool:
    if not isinstance(value,_FetchResult) or value.status not in {"found","missing","unstable","transport-error"} or type(value.content) is not bytes: return False
    values=(value.before_identity,value.after_identity,value.before_size,value.after_size,value.before_sha256,value.after_sha256)
    if value.status!="found": return not value.content and all(item is None for item in values)
    return type(value.before_identity) is str and type(value.after_identity) is str and type(value.before_size) is int and type(value.after_size) is int and type(value.before_sha256) is str and type(value.after_sha256) is str

__all__=["_BOOTSTRAP_PROTOCOL","_DeploymentAuthority","_DeploymentManifest","_FIXED_ENV","_FetchResult","_Invocation","_MANIFEST_NAME","_OPERATION_TABLE_BYTES","_OPERATION_TABLE_SHA256","_RESOURCE_DESCRIPTOR_NAME","_RTWinDriver","_SubprocessRTWinDriver","_SYNTHETIC_RESOURCE_DIALECT","_TORQUE_RESOURCE_DIALECT","_TextResult","_attest_local_effect_file","_is_fetch_result_closed","_is_text_result_closed","_operation","_parse_deployment_manifest","_parse_resource_descriptor","_render_qsub_argv","_resolve_deployment_authority","_resource_enactment"]
