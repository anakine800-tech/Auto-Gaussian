"""Composed Gaussian v5 file-carrier handoff primitives.

Only the Q6 delta is owned here. The already-qualified Q5 grammar remains the
single predecessor source, and every replacement must match exactly once.
"""
from __future__ import annotations

from hashlib import sha256

from . import _gaussian_handoff as _q5


def rewrite_exact(source: str, replacements: tuple[tuple[str, str], ...], label: str) -> str:
    """Apply an audited delta to one exact predecessor source."""
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError(f"{label} predecessor drift")
        source = source.replace(old, new, 1)
    return source


def rewrite_lines_exact(
    source: str,
    predecessor_sha256: str,
    result_sha256: str,
    edits,
    label: str,
) -> str:
    """Apply positional edits only to an exact predecessor source."""
    if sha256(source.encode()).hexdigest() != predecessor_sha256:
        raise ValueError(f"{label} predecessor digest drift")
    lines = source.splitlines(keepends=True)
    for start, stop, old, new in reversed(edits):
        if "".join(lines[start:stop]) != old:
            raise ValueError(f"{label} predecessor lines drift")
        lines[start:stop] = new.splitlines(keepends=True)
    result = "".join(lines)
    if sha256(result.encode()).hexdigest() != result_sha256:
        raise ValueError(f"{label} result digest drift")
    return result


_PROTOCOL_EDITS = ((1,
  2,
  'G_ENV="AUTO_G16_LAUNCH_HANDOFF_AUTH"\n',
  'G_CARRIER="v31-launch-carrier.json"\n'
  'G_CARRIER_PENDING="v31-launch-carrier.pending"\n'
  'G_QSUB_START="v31-qsub-invocation-start.json"\n'
  'G_QSUB_START_PENDING="v31-qsub-invocation-start.pending"\n'
  'G_ENTRY="gaussian.pbs"\n'
  'G_ENTRY_PENDING="gaussian.pbs.pending"\n'
  'G_ENTRY_TEMPLATE="gaussian-entry-template.pbs"\n'
  'G_CARRIER_PIN_PLACEHOLDER=b"__AUTO_G16_CARRIER_DESCRIPTOR_BASE64__"\n'
  'G_QSUB_ENV={"LANG":"C","LC_ALL":"C","PYTHONNOUSERSITE":"1","PYTHONUTF8":"1"}\n'),
 (3,
  4,
  'G_NAMES=("gaussian.pbs","gaussian-startup.json","gaussian-config.json",".auto-g16-v31-submit-intent")\n',
  'G_NAMES=(G_ENTRY_TEMPLATE,"gaussian-startup.json","gaussian-config.json",".auto-g16-v31-submit-intent")\n'),
 (81,
  87,
  'def g_carrier(value):\n'
  ' if type(value) is not str or not 0<len(value)<=4095 or re.fullmatch("[A-Za-z0-9_-]+",value) is '
  'None:g_fail()\n'
  ' '
  'raw=base64.b64decode((value+"="*((-len(value))%4)).encode("ascii"),altchars=b"-_",validate=True)\n'
  ' if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")!=value:g_fail()\n'
  ' v=g_parse(raw,3072,False);g_keys(v,"schema adapter_contract_version attempt_id '
  'workspace_binding_id program_execution_snapshot_id effect_intent_id workspace handoff '
  'submit_marker")\n'
  ' if v["schema"]!="auto-g16-v31-gaussian-launch-handoff-auth/1" or '
  'type(v["adapter_contract_version"]) is not int or v["adapter_contract_version"]!=4:g_fail()\n',
  'def g_carrier(raw):\n'
  ' v=g_parse(raw,65536);g_keys(v,"schema adapter_contract_version attempt_id workspace_binding_id '
  'program_execution_snapshot_id effect_intent_id workspace handoff submit_marker")\n'
  ' if v["schema"]!="auto-g16-v31-gaussian-launch-handoff-auth/1" or '
  'type(v["adapter_contract_version"]) is not int or v["adapter_contract_version"]!=5:g_fail()\n'),
 (132,
  132,
  '',
  'def g_read_published(parent,pending,final,cap,fds):\n'
  ' handles=[]\n'
  ' try:\n'
  '  for name in (pending,final):\n'
  '   try:handle=os.open(name,G_RF,dir_fd=parent)\n'
  '   except OSError:g_fail()\n'
  '   handles.append(handle);fds.append(handle)\n'
  '  stats=[os.fstat(x) for x in handles]\n'
  '  for s in stats:\n'
  '   if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=384 or '
  'not 0<s.st_size<=cap or s.st_nlink!=2:g_fail()\n'
  '  if g_ident(stats[0])!=g_ident(stats[1]):g_fail()\n'
  '  raw=b""\n'
  '  while len(raw)<stats[1].st_size:\n'
  '   chunk=os.read(handles[1],min(1048576,stats[1].st_size-len(raw)))\n'
  '   if not chunk:g_fail()\n'
  '   raw+=chunk\n'
  '  if os.read(handles[1],1):g_fail()\n'
  '  for handle,name in zip(handles,(pending,final)):\n'
  '   if g_ident(os.fstat(handle))!=g_ident(stats[1]) or '
  'g_ident(os.stat(name,dir_fd=parent,follow_symlinks=False))!=g_ident(stats[1]):g_fail()\n'
  '  return raw,stats[1]\n'
  ' except BaseException:\n'
  '  for handle in reversed(handles):\n'
  '   if handle in fds:fds.remove(handle)\n'
  '   os.close(handle)\n'
  '  raise\n'
  'def g_file_desc(path,parent_chain,token,name,s,raw):\n'
  ' return '
  '{"path":path+"/"+name,"parent_chain":parent_chain,"file_identity":g_statnode(s),**g_digest(raw),"physical_token_base64":g_b64(g_json(["v31-file/1",token,name,g_ident(s)]))}\n'
  'def g_render_entry(template,carrier_desc):\n'
  ' if type(template) is not bytes or template.count(G_CARRIER_PIN_PLACEHOLDER)!=1:g_fail()\n'
  ' pin=g_b64(g_json(carrier_desc)).encode("ascii")\n'
  ' if len(pin)>32768 or any(x in pin for x in (b"\\x00",b"\\r",b"\\n",b" ",b"\\t")):g_fail()\n'
  ' entry=template.replace(G_CARRIER_PIN_PLACEHOLDER,pin)\n'
  ' if not 0<len(entry)<=16384 or G_CARRIER_PIN_PLACEHOLDER in entry:g_fail()\n'
  ' return entry\n'),
 (164,
  165,
  ' if h["schema"]!="auto-g16-v31-gaussian-launch-handoff/1" or '
  'h["adapter_id"]!="auto-g16-v31-gaussian" or type(h["adapter_contract_version"]) is not int or '
  'h["adapter_contract_version"]!=4:g_fail()\n',
  ' if h["schema"]!="auto-g16-v31-gaussian-launch-handoff/1" or '
  'h["adapter_id"]!="auto-g16-v31-gaussian" or type(h["adapter_contract_version"]) is not int or '
  'h["adapter_contract_version"]!=5:g_fail()\n'),
 (201,
  202,
  ' return '
  '["-d",path,"-l","nodes=1:ppn="+str(r["cores"])+",mem="+str(r["memory_mb"])+"mb,walltime="+str(r["walltime_seconds"]),"-q","batch","-v",G_ENV+"=<carrier>","gaussian.pbs"]\n',
  ' return '
  '["-d",path,"-l","nodes=1:ppn="+str(r["cores"])+",mem="+str(r["memory_mb"])+"mb,walltime="+str(r["walltime_seconds"]),"-q","batch","gaussian.pbs"]\n'
  'def g_validate_qsub_start(v,c,carrier_desc,entry_desc,template):\n'
  ' g_keys(v,"schema attempt_id program_execution_snapshot_id effect_intent_id '
  'launch_handoff_pre_authority_id carrier entry raw_argv raw_argv_sha256 env_allowlist '
  'created_at")\n'
  ' if v["schema"]!="auto-g16-v31-gaussian-qsub-invocation-start/1":g_fail()\n'
  ' for key in ("attempt_id","program_execution_snapshot_id","effect_intent_id"):\n'
  '  if v[key]!=c[key]:g_fail()\n'
  ' if v["launch_handoff_pre_authority_id"]!=c["handoff"]["launch_handoff_pre_authority_id"] or '
  'v["carrier"]!=carrier_desc or v["entry"]!=entry_desc:g_fail()\n'
  ' w=c["workspace"];d=v["entry"]\n'
  ' g_keys(d,"path parent_chain file_identity size_bytes sha256 '
  'physical_token_base64");g_nodes(d["parent_chain"]);g_node(d["file_identity"]);g_desc({k:d[k] '
  'for k in ("sha256","size_bytes")},16384)\n'
  ' if d["path"]!=w["path"]+"/"+G_ENTRY or d["parent_chain"]!=c["handoff"]["parent_chain"] or '
  'g_file_token(d["physical_token_base64"],w["workspace_physical_token_base64"],G_ENTRY)[:3]!=[d["file_identity"]["device"],d["file_identity"]["inode"],d["size_bytes"]]:g_fail()\n'
  ' raw=v["raw_argv"]\n'
  ' if type(raw) is not list or len(raw)!=len(template)+1 or raw[1:]!=template:g_fail()\n'
  ' g_path(raw[0])\n'
  ' if "-v" in raw or "-V" in raw or v["env_allowlist"]!=G_QSUB_ENV:g_fail()\n'
  ' g_sha(v["raw_argv_sha256"])\n'
  ' if v["raw_argv_sha256"]!=hashlib.sha256(g_json(raw)).hexdigest():g_fail()\n'
  ' g_stamp(v["created_at"])\n'
  ' return g_record_id(v["schema"],v)\n'),
 (204,
  205,
  ' if v["schema"]!="auto-g16-v31-gaussian-launch-handoff-pre-authority/1" or '
  'v["carrier_contract"]!={"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","encoded_cap":4095,"decoded_cap":3072}:g_fail()\n',
  ' if v["schema"]!="auto-g16-v31-gaussian-launch-handoff-pre-authority/1" or '
  'v["carrier_contract"]!={"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","portable_name":G_CARRIER,"maximum_bytes":65536,"publication":"exclusive-pending-fsync-no-replace-link-directory-fsync"}:g_fail()\n'),
 (230,
  231,
  ' if type(t) is not list or len(t)!=9 or t[::2][:4]!=["-d","-l","-q","-v"] or t[1]!=a["path"] or '
  't[5]!="batch" or t[7]!=G_ENV+"=<carrier>" or t[8]!="gaussian.pbs":g_fail()\n',
  ' if type(t) is not list or len(t)!=7 or t[::2][:3]!=["-d","-l","-q"] or t[1]!=a["path"] or '
  't[5]!="batch" or t[6]!="gaussian.pbs" or "-v" in t or "-V" in t:g_fail()\n'),
 (235,
  236,
  ' value={"schema":"auto-g16-v31-gaussian-launch-handoff-pre-authority/1","scope":{k:h[k] for k '
  'in '
  '("attempt","program_execution_snapshot_id","effect_intent_id","resolved_server_profile_id")},"approvals":h["approvals"],"predecessor":h["predecessor"],"handoff":descriptor,"argv_template":template,"carrier_contract":{"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","encoded_cap":4095,"decoded_cap":3072}}\n',
  ' value={"schema":"auto-g16-v31-gaussian-launch-handoff-pre-authority/1","scope":{k:h[k] for k '
  'in '
  '("attempt","program_execution_snapshot_id","effect_intent_id","resolved_server_profile_id")},"approvals":h["approvals"],"predecessor":h["predecessor"],"handoff":descriptor,"argv_template":template,"carrier_contract":{"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","portable_name":G_CARRIER,"maximum_bytes":65536,"publication":"exclusive-pending-fsync-no-replace-link-directory-fsync"}}\n'))
PROTOCOL_SOURCE = rewrite_lines_exact(
    _q5.PROTOCOL_SOURCE,
    "48cb632b44c43740b6c8bf5cb0c5c08c8ef62b0244227bfcf4e3ad6daecf2d29",
    "51d2501e3edd12d8f8afa46255c488c76d38f6bb49a92db19c95263312fc85e5",
    _PROTOCOL_EDITS,
    "Gaussian file carrier",
)


def protocol_namespace():
    """Offline protocol validation; never starts the loader or a subprocess."""
    namespace = {"__name__": "gaussian_file_handoff_protocol"}
    exec(compile(PROTOCOL_SOURCE, "<gaussian-file-handoff-protocol>", "exec"), namespace)
    return namespace
