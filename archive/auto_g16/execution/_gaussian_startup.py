"""Gaussian v4 short entry; historical Gaussian material/5 stays untouched."""
from __future__ import annotations

import base64
from hashlib import sha256
import shlex
import zlib

from ._identity import ExecutionValueError, freeze_mapping
from auto_g16.transport._gaussian_handoff import PROTOCOL_SOURCE, protocol_namespace

_MATERIAL_SCHEMA = "v31-completion-rendering-material/6"
_Q_SCHEMA = "auto-g16-v31-publisher-qualification/5"
_Q_NAME = "v31-gaussian-publisher-qualification-v5.json"
_CONTRACT_SHA256 = "3da5596688473887b55f1851da4f64017952cbc33f5aab723f965b0d0383890b"
_HEADER = "# auto-g16-v31-scheduler/7"
_PAYLOAD_NAME = "gaussian-startup.json"
_PAYLOAD_SCHEMA = "auto-g16-v31-gaussian-startup-payload/1"

_LOADER_BODY = r'''
import sys,io,builtins,types
def g_semnode(v):
 if v is None:return ["null",None]
 if type(v) is bool:return ["boolean",v]
 if type(v) is int:return ["integer",v]
 if type(v) is str:return ["string",v]
 if type(v) is list:return ["sequence",[g_semnode(x) for x in v]]
 if type(v) is dict:return ["mapping",[[k,g_semnode(v[k])] for k in sorted(v)]]
 g_fail()
def g_sem(v):return hashlib.sha256(json.dumps(g_semnode(v),ensure_ascii=False,separators=(",",":"),sort_keys=False).encode()).hexdigest()
def g_id(domain,v):return str(uuid.uuid5(uuid.UUID("4fbc452d-47a8-5fa6-b4ef-c25de2aeb6ba"),"auto-g16.execution\x00v1\x00"+domain+"\x00"+json.dumps(g_semnode(v),ensure_ascii=False,separators=(",",":"),sort_keys=False)))
def g_loader(constants):
 g_keys(constants,"schema attempt_id workspace_binding_id workspace project_physical_binding_id resolved_server_profile_id payload wrapper_source server_python resources")
 if constants["schema"]!="auto-g16-v31-gaussian-startup-invocation/1":g_fail()
 if [k for k in os.environ if k.startswith("AUTO_G16_LAUNCH_HANDOFF") ]!=[G_ENV]:g_fail()
 c=g_carrier(os.environ[G_ENV]);w=c["workspace"]
 for k in ("attempt_id","workspace_binding_id"):
  if c[k]!=constants[k]:g_fail()
 if w["path"]!=constants["workspace"]:g_fail()
 py=constants["server_python"];g_keys(py,"path sha256 size_bytes")
 if os.path.abspath(sys.executable)!=py["path"]:g_fail()
 # The interpreter is the only pre-entry executable read; no publisher probe.
 parts=py["path"].split("/")[1:];pfds=[os.open("/",G_DF)]
 try:
  for name in parts[:-1]:pfds.append(os.open(name,G_DF,dir_fd=pfds[-1]))
  ancestry=[g_statnode(os.fstat(fd)) for fd in pfds]
  pfd=os.open(parts[-1],G_RF,dir_fd=pfds[-1]);pfds.append(pfd);before=os.fstat(pfd)
  if not stat.S_ISREG(before.st_mode) or before.st_size!=py["size_bytes"]:g_fail()
  digest=hashlib.sha256();count=0
  while True:
   block=os.read(pfd,1048576)
   if not block:break
   count+=len(block);digest.update(block)
   if count>py["size_bytes"]:g_fail()
  if count!=py["size_bytes"] or digest.hexdigest()!=py["sha256"] or g_ident(before)!=g_ident(os.fstat(pfd)) or g_ident(before)!=g_ident(os.stat(parts[-1],dir_fd=pfds[-2],follow_symlinks=False)):g_fail()
  for i,name in enumerate(parts[:-1]):
   if g_statnode(os.stat(name,dir_fd=pfds[i],follow_symlinks=False))!=ancestry[i+1]:g_fail()
 finally:
  for fd in reversed(pfds):os.close(fd)
 fds=[os.open(".",G_DF)];parent=fds[0]
 try:
  def cwd_check():
   s=os.fstat(parent)
   if {**g_statnode(s),"uid":s.st_uid,"mode":stat.S_IMODE(s.st_mode)}!=w["directory_identity"] or s.st_uid!=os.getuid():g_fail()
  cwd_check();token=w["workspace_physical_token_base64"]
  raw,_=g_read(parent,"v31-launch-handoff.json",c["handoff"],token,fds);h=g_handoff(raw,c)
  if h["resolved_server_profile_id"]!=constants["resolved_server_profile_id"] or h["project"]["project_physical_binding_id"]!=constants["project_physical_binding_id"]:g_fail()
  hd={k:v for k,v in c["handoff"].items() if k!="launch_handoff_pre_authority_id"}
  _,pre_id=g_pre_authority(h,hd,g_template(w["path"],constants["resources"]))
  if pre_id!=c["handoff"]["launch_handoff_pre_authority_id"]:g_fail()
  marker,_=g_read(parent,G_NAMES[3],c["submit_marker"],token,fds)
  if g_parse(marker,65536)!={k:c[k] for k in ("program_execution_snapshot_id","effect_intent_id")}:g_fail()
  job=os.environ.get("PBS_JOBID","")
  if re.fullmatch("[A-Za-z0-9][A-Za-z0-9._-]*",job) is None:g_fail()
  stages=[];observed=None;source_desc=None;config_desc=None
  def publish(stage):
   if len(stages)>=len(G_STAGES) or stage!=G_STAGES[len(stages)]:g_fail()
   value={"schema":"auto-g16-v31-gaussian-startup-stage/1","stage":stage,**{k:c[k] for k in ("attempt_id","workspace_binding_id","program_execution_snapshot_id","effect_intent_id")},"job_id":job,"payload_expected":{"portable_name":G_NAMES[1],**constants["payload"]},"payload_observed":observed,"wrapper_source":source_desc,"config":config_desc,"previous_stage_sha256":None if not stages else hashlib.sha256(stages[-1]).hexdigest(),"created_at":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
   data=g_json(g_stage(value));stem=".auto-g16-v31-"+stage
   g_publish(parent,stem+".pending",stem+".json",data,cwd_check);stages.append(data)
  publish("entry-start")
  entry,_=g_read(parent,G_NAMES[0],h["artifacts"]["entry"],token,fds)
  payload,ps=g_read(parent,G_NAMES[1],h["artifacts"]["payload"],token,fds)
  cfg,_=g_read(parent,G_NAMES[2],h["artifacts"]["config"],token,fds)
  if g_digest(payload)!=constants["payload"]:g_fail()
  source,config,decoded=g_payload(payload)
  if cfg!=config or g_digest(source)!=constants["wrapper_source"]:g_fail()
  binding=decoded["prebinding"];spec=decoded["spec"];material=decoded["material"]
  if material["schema"]!="v31-completion-rendering-material/6" or binding["binding_schema"]!="v31-completion-prebinding/7" or spec["program_kind"]!="gaussian" or type(spec["adapter_contract_version"]) is not int or spec["adapter_contract_version"]!=4:g_fail()
  if g_sem(binding)!=decoded["prebinding_sha256"] or g_sem(material)!=binding["rendering_material_sha256"] or g_sem(spec)!=binding["program_execution_spec_payload_sha256"]:g_fail()
  for k in ("attempt_id","workspace_binding_id","project_physical_binding_id","resolved_server_profile_id"):
   if binding[k]!=constants[k]:g_fail()
  if binding["cwd_binding"]!={"location_kind":"server","path":w["path"]} or binding["wrapper_source_sha256"]!=constants["wrapper_source"]["sha256"] or binding["wrapper_source_size_bytes"]!=constants["wrapper_source"]["size_bytes"]:g_fail()
  fields={k:v for k,v in binding.items() if k not in ("binding_schema","wrapper_source_sha256","wrapper_source_size_bytes","rendering_material_sha256")}
  arts=[]
  for role,name,form,data in (("scheduler-script",G_NAMES[0],"pbs-shell-utf8",entry),("startup-payload",G_NAMES[1],"canonical-json-utf8",payload)):
   arts.append({"logical_role":role,"portable_name":name,"format":form,**g_digest(data),"content_utf8":data.decode()})
  fields["scheduler_artifacts"]=arts
  # Same frozen semantic identity derivation as the snapshot owner.
  effect=g_id("program-effect-intent",fields)
  if c["effect_intent_id"]!=effect or c["program_execution_snapshot_id"]!=g_id("program-execution-snapshot",{"effect_intent_id":effect,**fields}):g_fail()
  observed={"device":ps.st_dev,"inode":ps.st_ino,"size_bytes":ps.st_size,"mtime_ns":ps.st_mtime_ns,"ctime_ns":ps.st_ctime_ns,"sha256":hashlib.sha256(payload).hexdigest()}
  source_desc=g_digest(source);config_desc=g_digest(config);publish("payload-verified")
  def wrapper_publish(stage):
   if stage not in ("wrapper-entered","launch-lock-handoff"):g_fail()
   publish(stage)
  context=types.MappingProxyType({"cwd_fd":parent,"workspace":w["path"],"workspace_token":token,"marker_bytes":marker,"marker_identity":tuple(g_file_token(c["submit_marker"]["physical_token_base64"],token,G_NAMES[3])),"job_id":job})
  filename="<auto-g16-v31-gaussian-wrapper>";code=compile(source,filename,"exec",dont_inherit=True,optimize=0)
  namespace={"__name__":"__main__","__file__":filename,"__package__":None,"__cached__":None,"__builtins__":builtins.__dict__,"__auto_g16_startup_context__":context,"__auto_g16_publish_stage__":wrapper_publish}
  sys.argv=[filename];sys.stdin=io.TextIOWrapper(io.BytesIO(base64.b64encode(config)+b"\n"),encoding="ascii",errors="strict",newline="")
  publish("wrapper-handoff");exec(code,namespace,namespace)
 finally:
  for fd in reversed(fds):os.close(fd)
if __name__=="__main__":
 try:
  if len(sys.argv)!=2:g_fail()
  g_loader(g_parse(g_un64(sys.argv[1]),8192))
 except Exception:
  sys.stderr.write('{"reason":"integrity","schema":"auto-g16-v31-gaussian-entry-refusal/1"}\n');raise SystemExit(125)
'''.lstrip()

# A fixed source-owned compression envelope keeps the *complete* qualified
# loader within the 16 KiB scheduler cap. No caller source/path is decoded.
_DECODED_LOADER_SOURCE = PROTOCOL_SOURCE + "\n" + _LOADER_BODY
_LOADER_SOURCE = (
    "import base64,zlib\nexec(compile(zlib.decompress(base64.b64decode("
    + repr(base64.b64encode(zlib.compress(_DECODED_LOADER_SOURCE.encode(), 9)).decode())
    + ")), '<auto-g16-v31-gaussian-loader>', 'exec', dont_inherit=True, optimize=0))\n"
)


def _wrapper_sources():
    from . import _gaussian_completion as predecessor
    wrapper, probe = predecessor._wrapper_sources()
    replacements = (
        (predecessor._MATERIAL_SCHEMA, _MATERIAL_SCHEMA),
        (predecessor._Q_SCHEMA, _Q_SCHEMA),
        ("v31-completion-prebinding/6", "v31-completion-prebinding/7"),
        ('spec["adapter_contract_version"]!=3', 'spec["adapter_contract_version"]!=4'),
        ('code=run(closed(un64(raw[:-1].decode("ascii"))))', 'code=run(closed(un64(raw[:-1].decode("ascii"))+b"\\n"))'),
        ('        exclusive(parent,"v31-completion-launch.lock",', '        __auto_g16_publish_stage__("launch-lock-handoff")\n        exclusive(parent,"v31-completion-launch.lock",'),
        ('def pin_directory(path):\n', 'def pin_directory(path):\n    ctx=__auto_g16_startup_context__\n    if path==ctx["workspace"]:\n        fd=os.dup(ctx["cwd_fd"]);return fd,ctx["workspace_token"],[fd]\n'),
        ('def reattest_directory(path,token,fds):\n', 'def reattest_directory(path,token,fds):\n    ctx=__auto_g16_startup_context__\n    if path==ctx["workspace"]:\n        if token!=ctx["workspace_token"] or len(fds)!=1 or identity(os.fstat(fds[0]))[:2]!=identity(os.fstat(ctx["cwd_fd"]))[:2]:fail("retained-cwd")\n        return\n'),
        ('def read_name(parent,name,limit=CAP,runtime=False):\n', 'def read_name(parent,name,limit=CAP,runtime=False):\n    ctx=__auto_g16_startup_context__\n    if name==".auto-g16-v31-submit-intent":\n        if identity(os.fstat(parent))[:2]!=identity(os.fstat(ctx["cwd_fd"]))[:2]:fail("retained-marker-parent")\n        return ctx["marker_bytes"],list(ctx["marker_identity"])\n'),
    )
    for old, new in replacements:
        if wrapper.count(old) != 1:
            raise ExecutionValueError("Gaussian short wrapper predecessor drift")
        wrapper = wrapper.replace(old, new, 1)
    wrapper = '__auto_g16_publish_stage__("wrapper-entered")\n' + wrapper
    return wrapper, probe


def _envelope(raw, schema):
    return {"schema": schema, "encoding": "base64-rfc4648-canonical", "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw), "data_base64": base64.b64encode(raw).decode()}


def _payload(artifacts):
    ns = protocol_namespace()
    if len(artifacts) != 2:
        raise ExecutionValueError("Gaussian short entry requires two artifacts")
    for item, role, name, form, cap in zip(artifacts, ("scheduler-script", "startup-payload"), ("gaussian.pbs", _PAYLOAD_NAME), ("pbs-shell-utf8", "canonical-json-utf8"), (16384, 8388608)):
        if set(item) != {"logical_role", "portable_name", "format", "sha256", "size_bytes", "content_utf8"} or (item["logical_role"], item["portable_name"], item["format"]) != (role, name, form):
            raise ExecutionValueError("Gaussian artifact tuple differs")
        raw = item["content_utf8"].encode()
        if type(item["size_bytes"]) is not int or len(raw) != item["size_bytes"] or not 0<len(raw)<=cap or sha256(raw).hexdigest()!=item["sha256"]:
            raise ExecutionValueError("Gaussian artifact bytes differ")
    source, raw_config, config = ns["g_payload"](artifacts[1]["content_utf8"].encode())
    if source != _wrapper_sources()[0].encode():
        raise ExecutionValueError("Gaussian wrapper source differs")
    return {"config": config, "config_bytes": raw_config, "wrapper_source": source}


def _render(config, deployment, resources, project_binding):
    from ._program_completion import _receipt_json
    from .project_provisioning import ProjectPhysicalBinding
    if type(project_binding) is not ProjectPhysicalBinding:
        raise ExecutionValueError("Gaussian short entry requires its Project binding")
    project_binding.assert_identity_closed()
    b=config["prebinding"]
    if b["project_physical_binding_id"]!=project_binding.project_physical_binding_id or b["cwd_binding"]["path"]!=project_binding.remote_project_dir+"/"+b["attempt_id"]:
        raise ExecutionValueError("Gaussian startup Project differs")
    wrapper=_wrapper_sources()[0].encode();cfg=_receipt_json(config)[:-1]
    raw=_receipt_json({"schema":_PAYLOAD_SCHEMA,"wrapper_source":_envelope(wrapper,"auto-g16-v31-gaussian-wrapper-source-bytes/1"),"config":_envelope(cfg,"auto-g16-v31-gaussian-wrapper-config-bytes/1")})
    protocol_namespace()["g_payload"](raw)
    py=deployment["trust_roots"]["server_python"]
    constants={"schema":"auto-g16-v31-gaussian-startup-invocation/1",**{k:b[k] for k in ("attempt_id","workspace_binding_id","project_physical_binding_id","resolved_server_profile_id")},"workspace":b["cwd_binding"]["path"],"payload":{"sha256":sha256(raw).hexdigest(),"size_bytes":len(raw)},"wrapper_source":{"sha256":sha256(wrapper).hexdigest(),"size_bytes":len(wrapper)},"resources":{"cores":resources.cores,"memory_mb":resources.memory_mb,"walltime_seconds":resources.walltime_seconds,"queue":resources.queue},"server_python":{"path":py["path"],"sha256":py["expected_sha256"],"size_bytes":py["expected_size_bytes"]}}
    lines=["#!/bin/bash",_HEADER,f"#PBS -l nodes=1:ppn={resources.cores}",f"#PBS -l mem={resources.memory_mb}mb",f"#PBS -l walltime={resources.walltime_seconds}"]
    if resources.queue is not None:lines.append(f"#PBS -q {resources.queue}")
    lines.append("exec "+" ".join(shlex.quote(x) for x in (py["path"],"-I","-S","-B","-c",_LOADER_SOURCE,base64.b64encode(_receipt_json(constants)).decode())))
    entry=("\n".join(lines)+"\n").encode()
    if len(entry)>16384:raise ExecutionValueError("Gaussian entry exceeds 16 KiB")
    result=tuple(freeze_mapping({"logical_role":role,"portable_name":name,"format":form,"sha256":sha256(data).hexdigest(),"size_bytes":len(data),"content_utf8":data.decode()},"Gaussian startup artifact") for role,name,form,data in (("scheduler-script","gaussian.pbs","pbs-shell-utf8",entry),("startup-payload",_PAYLOAD_NAME,"canonical-json-utf8",raw)))
    _payload(result)
    return result


def _derived_artifacts(snapshot):
    """The only config/marker staging source, deterministically snapshot-owned."""
    from ._program_completion import _receipt_json
    if (snapshot.program_execution_spec.program_kind,snapshot.program_execution_spec.adapter_contract_version)!=("gaussian",4):return ()
    cfg=_payload(snapshot.scheduler_artifacts)["config_bytes"]
    marker=_receipt_json({"program_execution_snapshot_id":snapshot.program_execution_snapshot_id,"effect_intent_id":snapshot.effect_intent_id})
    return tuple(({"artifact_kind":role,"logical_role":role,"portable_name":name,"format":"canonical-json-utf8","sha256":sha256(raw).hexdigest(),"size_bytes":len(raw)},raw) for role,name,raw in (("derived-config","gaussian-config.json",cfg),("submit-intent-marker",".auto-g16-v31-submit-intent",marker)))


def _review_disclosure(snapshot):
    """Expanded review only: no extra snapshot identity or operational authority."""
    return {
        "schema": "auto-g16-v31-gaussian-startup-review/1",
        "physical_handoff_contract_sha256": _CONTRACT_SHA256,
        "derived_stages": [declaration for declaration, _ in _derived_artifacts(snapshot)],
        "artifact_caps": {"gaussian.pbs": 16384, "gaussian-startup.json": 8388608, "gaussian-config.json": 6291456, ".auto-g16-v31-submit-intent": 65536},
        "stage_protocol": {
            "schema": "auto-g16-v31-gaussian-startup-stage/1",
            "ordered_stages": list(protocol_namespace()["G_STAGES"]),
            "files": [{"pending": ".auto-g16-v31-"+stage+".pending", "final": ".auto-g16-v31-"+stage+".json"} for stage in protocol_namespace()["G_STAGES"]],
            "maximum_bytes": 4096, "mode": 0o600,
            "hash_chain": "previous final marker SHA256; entry-start has null observed/source/config/previous",
            "publication": "exclusive-pending-fsync-no-replace-link-directory-fsync",
            "completion_authority": False,
            "completion_protocol": "unchanged v31-completion.json and exact output capture",
        },
        "handoff_protocol": {
            "schema": "auto-g16-v31-gaussian-launch-handoff/1",
            "carrier_name": "AUTO_G16_LAUNCH_HANDOFF_AUTH",
            "encoded_cap": 4095, "decoded_cap": 3072,
            "order": ["durable-stages", "handoff", "pre-authority", "carrier", "single-qsub", "post-receipt"],
        },
    }
