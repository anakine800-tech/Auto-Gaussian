"""Closed Gaussian v4 physical handoff primitives; no operational entry point.

The fixed source is also used by the qualified loader. It has no program,
scheduler, environment inheritance, retry, or completion decision authority.
"""
from __future__ import annotations

PROTOCOL_SOURCE = r'''
import base64,datetime,hashlib,json,os,re,stat,uuid
G_ENV="AUTO_G16_LAUNCH_HANDOFF_AUTH"
G_ROLES=("entry","payload","config","submit_marker")
G_NAMES=("gaussian.pbs","gaussian-startup.json","gaussian-config.json",".auto-g16-v31-submit-intent")
G_CAPS=(16384,8388608,6291456,65536)
G_STAGES=("entry-start","payload-verified","wrapper-handoff","wrapper-entered","launch-lock-handoff")
G_RF=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|getattr(os,"O_CLOEXEC",0)
G_DF=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0)
def g_fail():raise ValueError("gaussian-startup-integrity")
def g_keys(v,keys):
 if type(v) is not dict or set(v)!=set(keys.split()):g_fail()
def g_int(v,cap=2**63-1,low=0):
 if type(v) is not int or not low<=v<=cap:g_fail()
def g_text(v):
 if type(v) is not str or not v or len(v)>4096 or any(c in v for c in "\x00\r\n"):g_fail()
def g_sha(v):
 if type(v) is not str or re.fullmatch("[0-9a-f]{64}",v) is None:g_fail()
def g_json(v,lf=True):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")+(b"\n" if lf else b"")
def g_pairs(items):
 d={}
 for k,v in items:
  if k in d:g_fail()
  d[k]=v
 return d
def g_parse(raw,cap,lf=True):
 if type(raw) is not bytes or not 0<len(raw)<=cap or b"\x00" in raw:g_fail()
 v=json.loads(raw.decode("utf-8"),object_pairs_hook=g_pairs)
 if g_json(v,lf)!=raw:g_fail()
 return v
def g_b64(raw):return base64.b64encode(raw).decode("ascii")
def g_un64(v):
 if type(v) is not str:g_fail()
 raw=base64.b64decode(v.encode("ascii"),validate=True)
 if g_b64(raw)!=v:g_fail()
 return raw
def g_digest(raw):return {"sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw)}
def g_desc(v,cap):
 g_keys(v,"sha256 size_bytes");g_sha(v["sha256"]);g_int(v["size_bytes"],cap,1)
def g_node(v):
 g_keys(v,"device inode")
 for x in v.values():g_int(x)
def g_nodes(v):
 if type(v) is not list or not 1<=len(v)<=64:g_fail()
 for n in v:g_node(n)
def g_path(v):
 g_text(v)
 if not v.startswith("/") or os.path.normpath(v)!=v or "//" in v:g_fail()
def g_ident(s):return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def g_statnode(s):return {"device":s.st_dev,"inode":s.st_ino}
def g_dirnode(v):
 g_keys(v,"device inode uid mode");g_node({k:v[k] for k in ("device","inode")});g_int(v["uid"])
 if type(v["mode"]) is not int or v["mode"]!=448:g_fail()
def g_dir_token(v,path):
 t=g_parse(g_un64(v),16384)
 if type(t) is not list or len(t)!=3 or t[:2]!=["v31-directory/1",path] or type(t[2]) is not list or len(t[2])!=len(path.split("/")):g_fail()
 for n in t[2]:
  if type(n) is not list or len(n)!=2:g_fail()
  for x in n:g_int(x)
 return t
def g_file_token(v,workspace,name):
 t=g_parse(g_un64(v),32768)
 if type(t) is not list or len(t)!=4 or t[:3]!=["v31-file/1",workspace,name] or type(t[3]) is not list or len(t[3])!=5:g_fail()
 for x in t[3]:g_int(x)
 return t[3]
def g_envelope(v,schema,cap):
 g_keys(v,"schema encoding sha256 size_bytes data_base64")
 if v["schema"]!=schema or v["encoding"]!="base64-rfc4648-canonical":g_fail()
 g_desc({k:v[k] for k in ("sha256","size_bytes")},cap)
 if type(v["data_base64"]) is not str or len(v["data_base64"])>4*((cap+2)//3):g_fail()
 raw=g_un64(v["data_base64"])
 if g_digest(raw)!={k:v[k] for k in ("sha256","size_bytes")}:g_fail()
 return raw
def g_payload(raw):
 p=g_parse(raw,8388608);g_keys(p,"schema wrapper_source config")
 if p["schema"]!="auto-g16-v31-gaussian-startup-payload/1":g_fail()
 src=g_envelope(p["wrapper_source"],"auto-g16-v31-gaussian-wrapper-source-bytes/1",65536)
 cfg=g_envelope(p["config"],"auto-g16-v31-gaussian-wrapper-config-bytes/1",6291456)
 if src.startswith(b"\xef\xbb\xbf") or b"\x00" in src:g_fail()
 src.decode("utf-8");compile(src,"<auto-g16-v31-gaussian-wrapper>","exec",dont_inherit=True,optimize=0)
 c=g_parse(cfg,6291456,False);g_keys(c,"cores material prebinding prebinding_sha256 spec walltime_seconds")
 return src,cfg,c
def g_carrier(value):
 if type(value) is not str or not 0<len(value)<=4095 or re.fullmatch("[A-Za-z0-9_-]+",value) is None:g_fail()
 raw=base64.b64decode((value+"="*((-len(value))%4)).encode("ascii"),altchars=b"-_",validate=True)
 if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")!=value:g_fail()
 v=g_parse(raw,3072,False);g_keys(v,"schema adapter_contract_version attempt_id workspace_binding_id program_execution_snapshot_id effect_intent_id workspace handoff submit_marker")
 if v["schema"]!="auto-g16-v31-gaussian-launch-handoff-auth/1" or type(v["adapter_contract_version"]) is not int or v["adapter_contract_version"]!=4:g_fail()
 for k in ("attempt_id","workspace_binding_id","program_execution_snapshot_id","effect_intent_id"):g_text(v[k])
 if str(uuid.UUID(v["attempt_id"]))!=v["attempt_id"]:g_fail()
 w=v["workspace"];g_keys(w,"path parent_chain directory_identity workspace_physical_token_base64");g_path(w["path"]);g_nodes(w["parent_chain"]);g_dirnode(w["directory_identity"])
 token=w["workspace_physical_token_base64"];chain=g_dir_token(token,w["path"])[2]
 if chain!=[[n["device"],n["inode"]] for n in w["parent_chain"]]+[[w["directory_identity"]["device"],w["directory_identity"]["inode"]]] or not w["path"].endswith("/"+v["attempt_id"]):g_fail()
 for k,name in (("handoff","v31-launch-handoff.json"),("submit_marker",G_NAMES[3])):
  d=v[k];g_keys(d,"path parent_chain file_identity size_bytes sha256 physical_token_base64"+(" launch_handoff_pre_authority_id" if k=="handoff" else ""))
  g_nodes(d["parent_chain"]);g_node(d["file_identity"]);g_desc({x:d[x] for x in ("sha256","size_bytes")},65536)
  if d["path"]!=w["path"]+"/"+name or d["parent_chain"]!=w["parent_chain"]+[{x:w["directory_identity"][x] for x in ("device","inode")}]:g_fail()
  ident=g_file_token(d["physical_token_base64"],token,name)
  if ident[:3]!=[d["file_identity"]["device"],d["file_identity"]["inode"],d["size_bytes"]]:g_fail()
 g_text(v["handoff"]["launch_handoff_pre_authority_id"])
 return v
def g_stage(v):
 g_keys(v,"schema stage attempt_id job_id program_execution_snapshot_id effect_intent_id workspace_binding_id payload_expected payload_observed wrapper_source config previous_stage_sha256 created_at")
 if v["schema"]!="auto-g16-v31-gaussian-startup-stage/1" or v["stage"] not in G_STAGES:g_fail()
 for k in ("attempt_id","job_id","program_execution_snapshot_id","effect_intent_id","workspace_binding_id"):g_text(v[k])
 if str(uuid.UUID(v["attempt_id"]))!=v["attempt_id"] or re.fullmatch("[A-Za-z0-9][A-Za-z0-9._-]*",v["job_id"]) is None:g_fail()
 g_stamp(v["created_at"])
 p=v["payload_expected"];g_keys(p,"portable_name sha256 size_bytes")
 if p["portable_name"]!=G_NAMES[1]:g_fail()
 g_desc({k:p[k] for k in ("sha256","size_bytes")},8388608)
 if v["stage"]=="entry-start":
  if any(v[k] is not None for k in ("payload_observed","wrapper_source","config","previous_stage_sha256")):g_fail()
 else:
  g_sha(v["previous_stage_sha256"]);g_desc(v["wrapper_source"],65536);g_desc(v["config"],6291456)
  p=v["payload_observed"];g_keys(p,"device inode size_bytes mtime_ns ctime_ns sha256");g_sha(p["sha256"])
  for k in ("device","inode","size_bytes","mtime_ns","ctime_ns"):g_int(p[k])
  if any(p[k]!=v["payload_expected"][k] for k in ("sha256","size_bytes")):g_fail()
 if len(g_json(v))>4096:g_fail()
 return v
def g_stamp(v):
 if type(v) is not str or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z",v) is None:g_fail()
 datetime.datetime.strptime(v,"%Y-%m-%dT%H:%M:%S.%fZ")
def g_read(parent,name,d,token,fds):
 fd=os.open(name,G_RF,dir_fd=parent);fds.append(fd);s=os.fstat(fd)
 expect=g_file_token(d["physical_token_base64"],token,name)
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=384 or g_ident(s)!=expect or g_statnode(s)!=d["file_identity"] or s.st_size!=d["size_bytes"]:g_fail()
 raw=b""
 while len(raw)<s.st_size:
  chunk=os.read(fd,min(1048576,s.st_size-len(raw)))
  if not chunk:g_fail()
  raw+=chunk
 if os.read(fd,1) or g_ident(os.fstat(fd))!=expect or g_ident(os.stat(name,dir_fd=parent,follow_symlinks=False))!=expect or hashlib.sha256(raw).hexdigest()!=d["sha256"]:g_fail()
 return raw,s
def g_publish(parent,pending,final,raw,check):
 def regular(s):
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=384 or s.st_size!=len(raw):g_fail()
 for name in (pending,final):
  try:os.stat(name,dir_fd=parent,follow_symlinks=False)
  except FileNotFoundError:pass
  else:g_fail()
 check();fd=os.open(pending,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,384,dir_fd=parent)
 try:
  pos=0
  while pos<len(raw):
   n=os.write(fd,raw[pos:])
   if n<=0:g_fail()
   pos+=n
  os.fsync(fd);s=os.fstat(fd)
  regular(s)
  check()
  if g_ident(os.stat(pending,dir_fd=parent,follow_symlinks=False))!=g_ident(s):g_fail()
  os.link(pending,final,src_dir_fd=parent,dst_dir_fd=parent,follow_symlinks=False);os.fsync(parent)
  after=os.fstat(fd);other=os.open(final,G_RF,dir_fd=parent)
  try:
   regular(after);regular(os.fstat(other))
   if g_ident(os.fstat(other))!=g_ident(after) or g_statnode(after)!=g_statnode(s) or os.read(other,len(raw)+1)!=raw or any(g_ident(os.stat(n,dir_fd=parent,follow_symlinks=False))!=g_ident(after) for n in (pending,final)):g_fail()
   check()
   for current in (os.fstat(fd),os.fstat(other),os.stat(pending,dir_fd=parent,follow_symlinks=False),os.stat(final,dir_fd=parent,follow_symlinks=False)):
    regular(current)
    if g_ident(current)!=g_ident(after):g_fail()
   return after
  finally:os.close(other)
 finally:os.close(fd)
def g_handoff(raw,c):
 h=g_parse(raw,65536);g_keys(h,"schema adapter_id adapter_contract_version project attempt program_execution_snapshot_id effect_intent_id resolved_server_profile_id approvals predecessor artifacts created_at")
 if h["schema"]!="auto-g16-v31-gaussian-launch-handoff/1" or h["adapter_id"]!="auto-g16-v31-gaussian" or type(h["adapter_contract_version"]) is not int or h["adapter_contract_version"]!=4:g_fail()
 for k in ("program_execution_snapshot_id","effect_intent_id"):
  if h[k]!=c[k]:g_fail()
 g_text(h["resolved_server_profile_id"]);g_stamp(h["created_at"])
 w=c["workspace"];a=h["attempt"];g_keys(a,"attempt_id workspace_binding_id path parent_chain directory_identity workspace_physical_token_base64")
 if a!={"attempt_id":c["attempt_id"],"workspace_binding_id":c["workspace_binding_id"],**w}:g_fail()
 p=h["project"];g_keys(p,"project_id project_physical_binding_id path parent_chain directory_identity")
 for k in ("project_id","project_physical_binding_id"):g_text(p[k])
 g_dirnode(p["directory_identity"]);g_nodes(p["parent_chain"])
 if p["path"]!=w["path"].rsplit("/",1)[0] or p["parent_chain"]+[{k:p["directory_identity"][k] for k in ("device","inode")}]!=w["parent_chain"] or p["directory_identity"]["uid"]!=w["directory_identity"]["uid"]:g_fail()
 approvals=h["approvals"];g_keys(approvals,"scientific finite_batch operational_confirmation live_gate")
 for d in approvals.values():g_keys(d,"authority_id payload_sha256");g_text(d["authority_id"]);g_sha(d["payload_sha256"])
 pred=h["predecessor"];g_keys(pred,"transport_store_id store_instance_id runtime_attestation_id workspace_authority_id allocation_receipt_id allocation_receipt_payload_sha256 ordered_stage_authorities last_reattestation_id last_reattestation_payload_sha256 qsub_invocations_before_handoff")
 for k in ("transport_store_id","store_instance_id","runtime_attestation_id","workspace_authority_id","allocation_receipt_id","last_reattestation_id"):g_text(pred[k])
 for k in ("allocation_receipt_payload_sha256","last_reattestation_payload_sha256"):g_sha(pred[k])
 if type(pred["qsub_invocations_before_handoff"]) is not int or pred["qsub_invocations_before_handoff"]!=0 or type(pred["ordered_stage_authorities"]) is not list or len(pred["ordered_stage_authorities"])!=4:g_fail()
 art=h["artifacts"];g_keys(art,"entry payload config submit_marker")
 token=w["workspace_physical_token_base64"]
 ids=[]
 for k,name,cap,role,prior in zip(G_ROLES,G_NAMES,G_CAPS,("scheduler-entry","startup-payload","derived-config","submit-intent-marker"),pred["ordered_stage_authorities"]):
  d=art[k];g_keys(d,"role portable_name absolute_path parent_chain file_identity uid mode size_bytes sha256 artifact_authority_id stage_receipt_id stage_receipt_payload_sha256 physical_token_base64")
  if d["role"]!=role or d["portable_name"]!=name or d["absolute_path"]!=w["path"]+"/"+name or d["parent_chain"]!=c["handoff"]["parent_chain"] or type(d["mode"]) is not int or d["mode"]!=384 or d["uid"]!=w["directory_identity"]["uid"]:g_fail()
  g_int(d["uid"]);g_node(d["file_identity"]);g_desc({x:d[x] for x in ("sha256","size_bytes")},cap)
  g_text(d["artifact_authority_id"]);g_text(d["stage_receipt_id"]);g_sha(d["stage_receipt_payload_sha256"])
  ident=g_file_token(d["physical_token_base64"],token,name)
  if ident[:3]!=[d["file_identity"]["device"],d["file_identity"]["inode"],d["size_bytes"]]:g_fail()
  if prior!={"role":k,**{x:d[x] for x in ("artifact_authority_id","stage_receipt_id","stage_receipt_payload_sha256","physical_token_base64")}}:g_fail()
  ids.append(d["artifact_authority_id"]);ids.append(d["stage_receipt_id"])
 if len(ids)!=len(set(ids)):g_fail()
 d=art["submit_marker"]
 if c["submit_marker"]!={"path":d["absolute_path"],**{k:d[k] for k in ("parent_chain","file_identity","size_bytes","sha256","physical_token_base64")}}:g_fail()
 return h
def g_record_id(schema,payload):return schema+":"+hashlib.sha256(g_json(payload)).hexdigest()
def g_template(path,r):
 g_path(path);g_keys(r,"cores memory_mb walltime_seconds queue")
 for key in ("cores","memory_mb","walltime_seconds"):g_int(r[key],2**31-1,1)
 if r["queue"]!="batch":g_fail()
 return ["-d",path,"-l","nodes=1:ppn="+str(r["cores"])+",mem="+str(r["memory_mb"])+"mb,walltime="+str(r["walltime_seconds"]),"-q","batch","-v",G_ENV+"=<carrier>","gaussian.pbs"]
def g_validate_pre(v):
 g_keys(v,"schema scope approvals predecessor handoff argv_template carrier_contract")
 if v["schema"]!="auto-g16-v31-gaussian-launch-handoff-pre-authority/1" or v["carrier_contract"]!={"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","encoded_cap":4095,"decoded_cap":3072}:g_fail()
 scope=v["scope"];g_keys(scope,"attempt program_execution_snapshot_id effect_intent_id resolved_server_profile_id")
 for k in ("program_execution_snapshot_id","effect_intent_id","resolved_server_profile_id"):g_text(scope[k])
 a=scope["attempt"];g_keys(a,"attempt_id workspace_binding_id path parent_chain directory_identity workspace_physical_token_base64")
 g_text(a["workspace_binding_id"]);g_path(a["path"]);g_nodes(a["parent_chain"]);g_dirnode(a["directory_identity"])
 if str(uuid.UUID(a["attempt_id"]))!=a["attempt_id"] or not a["path"].endswith("/"+a["attempt_id"]):g_fail()
 token=a["workspace_physical_token_base64"];nodes=a["parent_chain"]+[{k:a["directory_identity"][k] for k in ("device","inode")}]
 if g_dir_token(token,a["path"])[2]!=[[n["device"],n["inode"]] for n in nodes]:g_fail()
 g_keys(v["approvals"],"scientific finite_batch operational_confirmation live_gate")
 for d in v["approvals"].values():g_keys(d,"authority_id payload_sha256");g_text(d["authority_id"]);g_sha(d["payload_sha256"])
 p=v["predecessor"];g_keys(p,"transport_store_id store_instance_id runtime_attestation_id workspace_authority_id allocation_receipt_id allocation_receipt_payload_sha256 ordered_stage_authorities last_reattestation_id last_reattestation_payload_sha256 qsub_invocations_before_handoff")
 for k in ("transport_store_id","store_instance_id","runtime_attestation_id","workspace_authority_id","allocation_receipt_id","last_reattestation_id"):g_text(p[k])
 for k in ("allocation_receipt_payload_sha256","last_reattestation_payload_sha256"):g_sha(p[k])
 if type(p["qsub_invocations_before_handoff"]) is not int or p["qsub_invocations_before_handoff"]!=0 or type(p["ordered_stage_authorities"]) is not list or len(p["ordered_stage_authorities"])!=4:g_fail()
 ids=[]
 for role,name,row in zip(G_ROLES,G_NAMES,p["ordered_stage_authorities"]):
  g_keys(row,"role artifact_authority_id stage_receipt_id stage_receipt_payload_sha256 physical_token_base64")
  if row["role"]!=role:g_fail()
  for k in ("artifact_authority_id","stage_receipt_id"):g_text(row[k]);ids.append(row[k])
  g_sha(row["stage_receipt_payload_sha256"]);g_file_token(row["physical_token_base64"],token,name)
 if len(ids)!=len(set(ids)):g_fail()
 d=v["handoff"];g_keys(d,"path parent_chain file_identity size_bytes sha256 physical_token_base64")
 g_nodes(d["parent_chain"]);g_node(d["file_identity"]);g_desc({k:d[k] for k in ("sha256","size_bytes")},65536)
 if d["path"]!=a["path"]+"/v31-launch-handoff.json" or d["parent_chain"]!=nodes:g_fail()
 if g_file_token(d["physical_token_base64"],token,"v31-launch-handoff.json")[:3]!=[d["file_identity"]["device"],d["file_identity"]["inode"],d["size_bytes"]]:g_fail()
 t=v["argv_template"]
 if type(t) is not list or len(t)!=9 or t[::2][:4]!=["-d","-l","-q","-v"] or t[1]!=a["path"] or t[5]!="batch" or t[7]!=G_ENV+"=<carrier>" or t[8]!="gaussian.pbs":g_fail()
 if type(t[3]) is not str or re.fullmatch(r"nodes=1:ppn=[1-9][0-9]*,mem=[1-9][0-9]*mb,walltime=[1-9][0-9]*",t[3]) is None:g_fail()
 return g_record_id(v["schema"],v)
def g_pre_authority(h,descriptor,template):
 g_keys(h,"schema adapter_id adapter_contract_version project attempt program_execution_snapshot_id effect_intent_id resolved_server_profile_id approvals predecessor artifacts created_at")
 value={"schema":"auto-g16-v31-gaussian-launch-handoff-pre-authority/1","scope":{k:h[k] for k in ("attempt","program_execution_snapshot_id","effect_intent_id","resolved_server_profile_id")},"approvals":h["approvals"],"predecessor":h["predecessor"],"handoff":descriptor,"argv_template":template,"carrier_contract":{"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","encoded_cap":4095,"decoded_cap":3072}}
 identity=g_validate_pre(value)
 # Validate the entire predecessor handoff too. This ephemeral descriptor is
 # a schema check, never a persisted downstream carrier or pre-authority field.
 marker=h["artifacts"]["submit_marker"];a=h["attempt"]
 check={"attempt_id":a["attempt_id"],"workspace_binding_id":a["workspace_binding_id"],"workspace":{k:v for k,v in a.items() if k not in ("attempt_id","workspace_binding_id")},"program_execution_snapshot_id":h["program_execution_snapshot_id"],"effect_intent_id":h["effect_intent_id"],"handoff":descriptor,"submit_marker":{"path":marker["absolute_path"],**{k:marker[k] for k in ("parent_chain","file_identity","size_bytes","sha256","physical_token_base64")}}}
 g_handoff(g_json(h),check)
 return value,identity
'''.lstrip()


def protocol_namespace():
    """Offline protocol validation; never starts the loader or a subprocess."""
    namespace = {"__name__": "gaussian_handoff_protocol"}
    exec(compile(PROTOCOL_SOURCE, "<gaussian-handoff-protocol>", "exec"), namespace)
    return namespace
