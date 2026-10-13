"""Gaussian v4-only native handoff source and acyclic record builders."""
from __future__ import annotations

from typing import Final

from ._gaussian_handoff import PROTOCOL_SOURCE


# The qualified server source keeps qsub itself bounded to the generic 30-second
# operation-table limit.  The controller gives the enclosing Gaussian submit
# effect a separate 90-second budget for pre-submit identity checks, atomic
# receipt publication, and transport of the response.  Keep these values
# explicit so a future source or controller change cannot silently recreate the
# former 30/30 deadline collision.
QSUB_CHILD_TIMEOUT_SECONDS: Final = 30
RECEIPT_PERSISTENCE_BUDGET_SECONDS: Final = 90
SUBMIT_EFFECT_TIMEOUT_SECONDS: Final = (
    QSUB_CHILD_TIMEOUT_SECONDS + RECEIPT_PERSISTENCE_BUDGET_SECONDS
)
_QSUB_CHILD_DEADLINE_SOURCE: Final = (
    b"deadline=time.monotonic()+30"
)

SUBMIT_SOURCE = r'''
def g_carrier_value(c):
 value=base64.urlsafe_b64encode(g_json(c,False)).decode("ascii").rstrip("=")
 if g_carrier(value)!=c:g_fail()
 return value
def g_submit(b,p,roots,fd,projectfd):
 original=p["request_payload"];g_keys(original,"scheduler_portable_name scheduler_artifact_authority_id program_input_artifact_authority_ids startup_payload_artifact_authority_ids handoff_artifact_authority_ids")
 if original["scheduler_portable_name"]!="gaussian.pbs":g_fail()
 template=g_template(b["remote_workspace"],p["resources"])
 context=p["launch_context"];g_keys(context,"project_id project_physical_binding_id workspace_binding_id approvals predecessor stages")
 rows=context["stages"]
 if type(rows) is not list or len(rows)!=4:g_fail()
 if original["scheduler_artifact_authority_id"]!=rows[0]["artifact_authority_id"] or original["startup_payload_artifact_authority_ids"]!=[rows[1]["artifact_authority_id"]] or original["handoff_artifact_authority_ids"]!=[x["artifact_authority_id"] for x in rows[2:]] or type(original["program_input_artifact_authority_ids"]) is not list or len(original["program_input_artifact_authority_ids"])!=1:g_fail()
 pred=context["predecessor"];g_keys(pred,"transport_store_id store_instance_id runtime_attestation_id workspace_authority_id allocation_receipt_id allocation_receipt_payload_sha256")
 path=b["remote_workspace"];token=b["workspace_physical_token"];chain=g_dir_token(token,path)[2]
 parent_chain=[{"device":x[0],"inode":x[1]} for x in chain]
 wstat=os.fstat(fd);pstat=os.fstat(projectfd)
 if wstat.st_uid!=os.getuid() or pstat.st_uid!=os.getuid() or stat.S_IMODE(wstat.st_mode)!=448 or stat.S_IMODE(pstat.st_mode)!=448:g_fail()
 workspace={"path":path,"parent_chain":parent_chain[:-1],"directory_identity":{**g_statnode(wstat),"uid":wstat.st_uid,"mode":448},"workspace_physical_token_base64":token}
 files=[];art={};retained=[]
 try:
  science=[x for x in p["staged"] if x["artifact_kind"]=="program-input"]
  if len(science)!=1 or len(p["staged"])!=5:g_fail()
  scientific=science[0];si=g_file_token(scientific["artifact_physical_token"],token,scientific["portable_name"])
  sd={"file_identity":{"device":si[0],"inode":si[1]},"size_bytes":scientific["size_bytes"],"sha256":scientific["sha256"],"physical_token_base64":scientific["artifact_physical_token"]}
  scientific_raw,ss=g_read(fd,scientific["portable_name"],sd,token,files)
  scientific_retained=(scientific["portable_name"],files[-1],g_ident(ss),scientific_raw)
  for key,name,cap,role,row in zip(G_ROLES,G_NAMES,G_CAPS,("scheduler-entry","startup-payload","derived-config","submit-intent-marker"),rows):
   g_keys(row,"role artifact_authority_id stage_receipt_id stage_receipt_payload_sha256 physical_token_base64")
   if row["role"]!=key:g_fail()
   matches=[x for x in p["staged"] if x["portable_name"]==name]
   if len(matches)!=1:g_fail()
   staged=matches[0];physical=staged["artifact_physical_token"]
   if staged["artifact_kind"]!={"entry":"scheduler-script","payload":"startup-payload","config":"derived-config","submit_marker":"submit-intent-marker"}[key]:g_fail()
   if physical!=row["physical_token_base64"]:g_fail()
   ident=g_file_token(physical,token,name)
   d={"role":role,"portable_name":name,"absolute_path":path+"/"+name,"parent_chain":parent_chain,"file_identity":{"device":ident[0],"inode":ident[1]},"uid":os.getuid(),"mode":384,"size_bytes":staged["size_bytes"],"sha256":staged["sha256"],**{k:row[k] for k in ("artifact_authority_id","stage_receipt_id","stage_receipt_payload_sha256","physical_token_base64")}}
   g_desc({k:d[k] for k in ("sha256","size_bytes")},cap)
   raw,s=g_read(fd,name,d,token,files);art[key]=d;retained.append((name,files[-1],g_ident(s),raw))
  # No second config source: bytes were already staged and receipted before SUBMIT.
  _,config,_=g_payload(retained[1][3])
  if config!=retained[2][3] or retained[3][3]!=g_json({k:b[k] for k in ("program_execution_snapshot_id","effect_intent_id")}):g_fail()
  def check():
   for name,expected_token,retained_fd,expected_stat in ((b["project_directory"],b["project_physical_identity"],projectfd,pstat),(path,token,fd,wstat)):
    expected={**g_statnode(expected_stat),"uid":expected_stat.st_uid,"mode":448}
    checkfd=named_directory(name,expected_token)
    try:
     for handle in (retained_fd,checkfd):
      current=os.fstat(handle)
      if {**g_statnode(current),"uid":current.st_uid,"mode":stat.S_IMODE(current.st_mode)}!=expected:g_fail()
    finally:os.close(checkfd)
   for name,handle,ident,raw in [scientific_retained]+retained:
    if g_ident(os.fstat(handle))!=ident or g_ident(os.stat(name,dir_fd=fd,follow_symlinks=False))!=ident:g_fail()
  check()
  reattested={"schema":"auto-g16-v31-gaussian-launch-reattestation/1","workspace":workspace,"project_physical_token":b["project_physical_identity"],"artifacts":art}
  rb=g_json(reattested);rid=g_record_id(reattested["schema"],reattested)
  g_publish(fd,"v31-launch-reattestation.pending","v31-launch-reattestation.json",rb,check)
  h={"schema":"auto-g16-v31-gaussian-launch-handoff/1","adapter_id":"auto-g16-v31-gaussian","adapter_contract_version":4,"project":{"project_id":context["project_id"],"project_physical_binding_id":context["project_physical_binding_id"],"path":b["project_directory"],"parent_chain":parent_chain[:-2],"directory_identity":{**g_statnode(pstat),"uid":pstat.st_uid,"mode":448}},"attempt":{"attempt_id":b["attempt_id"],"workspace_binding_id":context["workspace_binding_id"],**workspace},"program_execution_snapshot_id":b["program_execution_snapshot_id"],"effect_intent_id":b["effect_intent_id"],"resolved_server_profile_id":b["resolved_server_profile_id"],"approvals":context["approvals"],"predecessor":{**pred,"ordered_stage_authorities":rows,"last_reattestation_id":rid,"last_reattestation_payload_sha256":hashlib.sha256(rb).hexdigest(),"qsub_invocations_before_handoff":0},"artifacts":art,"created_at":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
  hb=g_json(h)
  if len(hb)>65536:g_fail()
  hs=g_publish(fd,"v31-launch-handoff.pending","v31-launch-handoff.json",hb,check)
  hd={"path":path+"/v31-launch-handoff.json","parent_chain":parent_chain,"file_identity":g_statnode(hs),**g_digest(hb),"physical_token_base64":g_b64(g_json(["v31-file/1",token,"v31-launch-handoff.json",g_ident(hs)]))}
  readback,_=g_read(fd,"v31-launch-handoff.json",hd,token,files)
  if readback!=hb:g_fail()
  retained.append(("v31-launch-handoff.json",files[-1],g_ident(hs),hb))
  pre,pid=g_pre_authority(h,hd,template)
  if g_validate_pre(pre)!=pid:g_fail()
  g_publish(fd,"v31-launch-pre-authority.pending","v31-launch-pre-authority.json",g_json(pre),check)
  md=art["submit_marker"];md={"path":md["absolute_path"],**{k:md[k] for k in ("parent_chain","file_identity","size_bytes","sha256","physical_token_base64")}}
  carrier={"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","adapter_contract_version":4,**{k:b[k] for k in ("attempt_id","program_execution_snapshot_id","effect_intent_id")},"workspace_binding_id":context["workspace_binding_id"],"workspace":workspace,"handoff":{**hd,"launch_handoff_pre_authority_id":pid},"submit_marker":md}
  g_handoff(hb,carrier);value=g_carrier_value(carrier)
  args=list(template);args[7]=G_ENV+"="+value
  check();code=None;out=b"";err=b"";job=None;outcome="UNKNOWN"
  def post_check():
   if {**g_statnode(os.fstat(fd)),"uid":os.fstat(fd).st_uid,"mode":stat.S_IMODE(os.fstat(fd).st_mode)}!=workspace["directory_identity"]:g_fail()
  try:
   code,out,err=run_exact(roots["server_qsub"],args,fd,65536)
   candidate=out.decode("ascii").rstrip("\n")
   if code==0 and not err and PORTABLE.fullmatch(candidate) and out==candidate.encode("ascii")+b"\n":job=candidate;outcome="SUCCEEDED"
  finally:
   if G_QSUB_TRACE is not None:
    out=G_QSUB_TRACE.get("out",out);err=G_QSUB_TRACE.get("err",err);code=G_QSUB_TRACE.get("code",code)
   post={"schema":"auto-g16-v31-gaussian-qsub-launch-carrier-receipt/1","launch_handoff_pre_authority_id":pid,"carrier":{"name":G_ENV,"value":value,**g_digest(value.encode("ascii"))},"raw_argv":[roots["server_qsub"]["path"]]+args,"raw_argv_sha256":hashlib.sha256(g_json([roots["server_qsub"]["path"]]+args)).hexdigest(),"env_allowlist":ENV,"stdout_base64":g_b64(out),"stderr_base64":g_b64(err),"returncode":code,"outcome":outcome,"job_id":job}
   postraw=g_json(post)
   if len(postraw)>262144:g_fail()
   g_publish(fd,"v31-qsub-launch-carrier-receipt.pending","v31-qsub-launch-carrier-receipt.json",postraw,post_check)
  if outcome!="SUCCEEDED":g_fail()
  exclusive_write(fd,".auto-g16-v31-submitted",g_json({"program_execution_snapshot_id":b["program_execution_snapshot_id"],"effect_intent_id":b["effect_intent_id"],"job_id":job}))
  return {"job_id":job}
 finally:
  for handle in reversed(files):os.close(handle)
'''.lstrip()

SOURCE_NAME = "v31-gaussian-handoff-bootstrap-v1.py"


def source_bytes():
    """A separate qualified source generation; original bootstrap stays exact."""
    from ._bridge import _PROGRAM_BOOTSTRAP_SOURCE

    source = _PROGRAM_BOOTSTRAP_SOURCE
    replacements = (
        ('keys(p,{"request_payload","executable","resources","staged"});', 'keys(p,{"request_payload","executable","resources","staged"}|({"launch_context"} if op=="SUBMIT_QSUB_ONCE" else set()));'),
        ('if not PORTABLE.fullmatch(name) or name in {".",".."}: fail("artifact-name")', 'if (not PORTABLE.fullmatch(name) and not (name==".auto-g16-v31-submit-intent" and original["artifact_kind"]=="submit-intent-marker")) or name in {".",".."}: fail("artifact-name")'),
        ('        if op=="SUBMIT_QSUB_ONCE":\n', '        if op=="SUBMIT_QSUB_ONCE":\n            return respond(op,g_submit(b,p,roots,fd,projectfd))\n'),
        ('def main():\n', PROTOCOL_SOURCE + "\n" + SUBMIT_SOURCE + '\nG_QSUB_TRACE={}\ndef main():\n'),
        ('        selector.close()\n', '        if G_QSUB_TRACE is not None:\n            G_QSUB_TRACE.update(out=bytes(outputs["out"]),err=bytes(outputs["err"]),code=proc.poll())\n        selector.close()\n'),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError("Gaussian native predecessor drift")
        source = source.replace(old, new, 1)
    return source.encode()


def assert_submit_timeout_contract() -> None:
    """Fail closed if the qualified child deadline and outer budget diverge."""
    if QSUB_CHILD_TIMEOUT_SECONDS != 30:
        raise ValueError("Gaussian qsub child deadline drift")
    if RECEIPT_PERSISTENCE_BUDGET_SECONDS != 90:
        raise ValueError("Gaussian receipt persistence budget drift")
    if SUBMIT_EFFECT_TIMEOUT_SECONDS != 120 or SUBMIT_EFFECT_TIMEOUT_SECONDS != (
        QSUB_CHILD_TIMEOUT_SECONDS + RECEIPT_PERSISTENCE_BUDGET_SECONDS
    ):
        raise ValueError("Gaussian submit timeout budget drift")
    if source_bytes().count(_QSUB_CHILD_DEADLINE_SOURCE) != 1:
        raise ValueError("Gaussian qsub child deadline source drift")
