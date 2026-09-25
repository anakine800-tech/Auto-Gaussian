"""Gaussian v5 file-carrier submit source composed from frozen Q5."""
from __future__ import annotations

from typing import Final

from . import _gaussian_submit as _q5
from ._gaussian_file_handoff import PROTOCOL_SOURCE, rewrite_lines_exact

QSUB_CHILD_TIMEOUT_SECONDS: Final = _q5.QSUB_CHILD_TIMEOUT_SECONDS
RECEIPT_PERSISTENCE_BUDGET_SECONDS: Final = _q5.RECEIPT_PERSISTENCE_BUDGET_SECONDS
SUBMIT_EFFECT_TIMEOUT_SECONDS: Final = _q5.SUBMIT_EFFECT_TIMEOUT_SECONDS
_QSUB_CHILD_DEADLINE_SOURCE: Final = _q5._QSUB_CHILD_DEADLINE_SOURCE

_SUBMIT_EDITS = ((0,
  4,
  'def g_carrier_value(c):\n'
  ' value=base64.urlsafe_b64encode(g_json(c,False)).decode("ascii").rstrip("=")\n'
  ' if g_carrier(value)!=c:g_fail()\n'
  ' return value\n',
  ''),
 (56,
  57,
  '  '
  'h={"schema":"auto-g16-v31-gaussian-launch-handoff/1","adapter_id":"auto-g16-v31-gaussian","adapter_contract_version":4,"project":{"project_id":context["project_id"],"project_physical_binding_id":context["project_physical_binding_id"],"path":b["project_directory"],"parent_chain":parent_chain[:-2],"directory_identity":{**g_statnode(pstat),"uid":pstat.st_uid,"mode":448}},"attempt":{"attempt_id":b["attempt_id"],"workspace_binding_id":context["workspace_binding_id"],**workspace},"program_execution_snapshot_id":b["program_execution_snapshot_id"],"effect_intent_id":b["effect_intent_id"],"resolved_server_profile_id":b["resolved_server_profile_id"],"approvals":context["approvals"],"predecessor":{**pred,"ordered_stage_authorities":rows,"last_reattestation_id":rid,"last_reattestation_payload_sha256":hashlib.sha256(rb).hexdigest(),"qsub_invocations_before_handoff":0},"artifacts":art,"created_at":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}\n',
  '  '
  'h={"schema":"auto-g16-v31-gaussian-launch-handoff/1","adapter_id":"auto-g16-v31-gaussian","adapter_contract_version":5,"project":{"project_id":context["project_id"],"project_physical_binding_id":context["project_physical_binding_id"],"path":b["project_directory"],"parent_chain":parent_chain[:-2],"directory_identity":{**g_statnode(pstat),"uid":pstat.st_uid,"mode":448}},"attempt":{"attempt_id":b["attempt_id"],"workspace_binding_id":context["workspace_binding_id"],**workspace},"program_execution_snapshot_id":b["program_execution_snapshot_id"],"effect_intent_id":b["effect_intent_id"],"resolved_server_profile_id":b["resolved_server_profile_id"],"approvals":context["approvals"],"predecessor":{**pred,"ordered_stage_authorities":rows,"last_reattestation_id":rid,"last_reattestation_payload_sha256":hashlib.sha256(rb).hexdigest(),"qsub_invocations_before_handoff":0},"artifacts":art,"created_at":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}\n'),
 (68,
  74,
  '  '
  'carrier={"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","adapter_contract_version":4,**{k:b[k] '
  'for k in '
  '("attempt_id","program_execution_snapshot_id","effect_intent_id")},"workspace_binding_id":context["workspace_binding_id"],"workspace":workspace,"handoff":{**hd,"launch_handoff_pre_authority_id":pid},"submit_marker":md}\n'
  '  g_handoff(hb,carrier);value=g_carrier_value(carrier)\n'
  '  args=list(template);args[7]=G_ENV+"="+value\n'
  '  check();code=None;out=b"";err=b"";job=None;outcome="UNKNOWN"\n'
  '  def post_check():\n'
  '   if '
  '{**g_statnode(os.fstat(fd)),"uid":os.fstat(fd).st_uid,"mode":stat.S_IMODE(os.fstat(fd).st_mode)}!=workspace["directory_identity"]:g_fail()\n',
  '  '
  'carrier={"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","adapter_contract_version":5,**{k:b[k] '
  'for k in '
  '("attempt_id","program_execution_snapshot_id","effect_intent_id")},"workspace_binding_id":context["workspace_binding_id"],"workspace":workspace,"handoff":{**hd,"launch_handoff_pre_authority_id":pid},"submit_marker":md}\n'
  '  g_handoff(hb,carrier);carrier_raw=g_json(carrier);g_carrier(carrier_raw)\n'
  '  cs=g_publish(fd,G_CARRIER_PENDING,G_CARRIER,carrier_raw,check)\n'
  '  cd=g_file_desc(path,parent_chain,token,G_CARRIER,cs,carrier_raw)\n'
  '  readback,_=g_read(fd,G_CARRIER,cd,token,files)\n'
  '  if readback!=carrier_raw:g_fail()\n'
  '  retained.append((G_CARRIER,files[-1],g_ident(cs),carrier_raw))\n'
  '  entry_raw=g_render_entry(retained[0][3],cd)\n'
  '  es=g_publish(fd,G_ENTRY_PENDING,G_ENTRY,entry_raw,check)\n'
  '  ed=g_file_desc(path,parent_chain,token,G_ENTRY,es,entry_raw)\n'
  '  readback,_=g_read(fd,G_ENTRY,ed,token,files)\n'
  '  if readback!=entry_raw:g_fail()\n'
  '  retained.append((G_ENTRY,files[-1],g_ident(es),entry_raw))\n'
  '  args=list(template);raw_argv=[roots["server_qsub"]["path"]]+args\n'
  '  if ENV!=G_QSUB_ENV:g_fail()\n'
  '  start={"schema":"auto-g16-v31-gaussian-qsub-invocation-start/1",**{k:b[k] for k in '
  '("attempt_id","program_execution_snapshot_id","effect_intent_id")},"launch_handoff_pre_authority_id":pid,"carrier":cd,"entry":ed,"raw_argv":raw_argv,"raw_argv_sha256":hashlib.sha256(g_json(raw_argv)).hexdigest(),"env_allowlist":ENV,"created_at":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}\n'
  '  sid=g_validate_qsub_start(start,carrier,cd,ed,template);start_raw=g_json(start)\n'
  '  ss=g_publish(fd,G_QSUB_START_PENDING,G_QSUB_START,start_raw,check)\n'
  '  sd=g_file_desc(path,parent_chain,token,G_QSUB_START,ss,start_raw)\n'
  '  readback,_=g_read(fd,G_QSUB_START,sd,token,files)\n'
  '  if readback!=start_raw:g_fail()\n'
  '  retained.append((G_QSUB_START,files[-1],g_ident(ss),start_raw))\n'
  '  check();code=None;out=b"";err=b"";job=None;outcome="UNKNOWN";returned=False\n'
  '  if G_QSUB_TRACE is not None:G_QSUB_TRACE.clear()\n'),
 (75,
  76,
  '   code,out,err=run_exact(roots["server_qsub"],args,fd,65536)\n',
  '   code,out,err=run_exact(roots["server_qsub"],args,fd,65536);returned=True\n'),
 (78, 78, '', '   elif code is not None and code!=0:outcome="FAILED"\n'),
 (81,
  82,
  '   '
  'post={"schema":"auto-g16-v31-gaussian-qsub-launch-carrier-receipt/1","launch_handoff_pre_authority_id":pid,"carrier":{"name":G_ENV,"value":value,**g_digest(value.encode("ascii"))},"raw_argv":[roots["server_qsub"]["path"]]+args,"raw_argv_sha256":hashlib.sha256(g_json([roots["server_qsub"]["path"]]+args)).hexdigest(),"env_allowlist":ENV,"stdout_base64":g_b64(out),"stderr_base64":g_b64(err),"returncode":code,"outcome":outcome,"job_id":job}\n',
  '   if returned and outcome!="SUCCEEDED" and code is not None and code!=0:outcome="FAILED"\n'
  '   if not returned:outcome="UNKNOWN";job=None\n'
  '   '
  'post={"schema":"auto-g16-v31-gaussian-qsub-launch-carrier-receipt/2","qsub_invocation_start_id":sid,"launch_handoff_pre_authority_id":pid,"carrier":cd,"raw_argv":raw_argv,"raw_argv_sha256":hashlib.sha256(g_json(raw_argv)).hexdigest(),"env_allowlist":ENV,"invocation_status":"returned" '
  'if returned else '
  '"interrupted-or-timeout","stdout_base64":g_b64(out),"stderr_base64":g_b64(err),"returncode":code,"outcome":outcome,"job_id":job}\n'),
 (84,
  85,
  '   '
  'g_publish(fd,"v31-qsub-launch-carrier-receipt.pending","v31-qsub-launch-carrier-receipt.json",postraw,post_check)\n',
  '   '
  'g_publish(fd,"v31-qsub-launch-carrier-receipt.pending","v31-qsub-launch-carrier-receipt.json",postraw,check)\n'))
SUBMIT_SOURCE = rewrite_lines_exact(
    _q5.SUBMIT_SOURCE,
    "c1c59afc88f487891ae663cd9a8a71d70e42a13fa39121788c5e2bd758f15b37",
    "539e7f02bc0e07b1cdd154158ecddb21bd9f24ba07ca81308f325ef4293dbc3f",
    _SUBMIT_EDITS,
    "Gaussian file-carrier submit",
)
SOURCE_NAME = "v31-gaussian-file-carrier-bootstrap-v2.py"


def source_bytes():
    """Replace only the exact Q5 embedded protocol and submit body."""
    source = _q5.source_bytes()
    old = (_q5.PROTOCOL_SOURCE + "\n" + _q5.SUBMIT_SOURCE).encode()
    new = (PROTOCOL_SOURCE + "\n" + SUBMIT_SOURCE).encode()
    if source.count(old) != 1:
        raise ValueError("Gaussian native predecessor drift")
    return source.replace(old, new, 1)


def assert_submit_timeout_contract() -> None:
    """Keep the Q5 child deadline and its separate persistence margin."""
    if QSUB_CHILD_TIMEOUT_SECONDS != 30:
        raise ValueError("Gaussian qsub child deadline drift")
    if RECEIPT_PERSISTENCE_BUDGET_SECONDS != 90:
        raise ValueError("Gaussian receipt persistence budget drift")
    if SUBMIT_EFFECT_TIMEOUT_SECONDS != 120 or SUBMIT_EFFECT_TIMEOUT_SECONDS != (
        QSUB_CHILD_TIMEOUT_SECONDS + RECEIPT_PERSISTENCE_BUDGET_SECONDS
    ):
        raise ValueError("Gaussian submit timeout budget drift")
    if source_bytes().count(_QSUB_CHILD_DEADLINE_SOURCE) != 1:
        raise ValueError("Gaussian file-carrier child deadline source drift")
