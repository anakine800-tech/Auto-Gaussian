"""Gaussian v5 file-carrier entry composed from the frozen Q5 entry."""
from __future__ import annotations

import base64
from hashlib import sha256
import shlex
import zlib

from ._identity import ExecutionValueError, freeze_mapping
from . import _gaussian_startup as _q5
from auto_g16.transport._gaussian_file_handoff import PROTOCOL_SOURCE, protocol_namespace, rewrite_exact, rewrite_lines_exact

_MATERIAL_SCHEMA = "v31-completion-rendering-material/7"
_Q_SCHEMA = "auto-g16-v31-publisher-qualification/6"
_Q_NAME = "v31-gaussian-publisher-qualification-v6.json"
_PREDECESSOR_CONTRACT_SHA256 = _q5._CONTRACT_SHA256
_CONTRACT_SHA256 = "ba7135e3b3b5595dad74bd6c3bba4ddf5a641580c48baf6a30412eceb23511e0"
_HEADER = "# auto-g16-v31-scheduler/8"
_PAYLOAD_NAME = _q5._PAYLOAD_NAME
_PAYLOAD_SCHEMA = _q5._PAYLOAD_SCHEMA

_LOADER_EDITS = ((11, 12, 'def g_loader(constants):\n', 'def g_loader(constants,carrier_pin):\n'),
 (14,
  19,
  ' if [k for k in os.environ if k.startswith("AUTO_G16_LAUNCH_HANDOFF") ]!=[G_ENV]:g_fail()\n'
  ' c=g_carrier(os.environ[G_ENV]);w=c["workspace"]\n'
  ' for k in ("attempt_id","workspace_binding_id"):\n'
  '  if c[k]!=constants[k]:g_fail()\n'
  ' if w["path"]!=constants["workspace"]:g_fail()\n',
  ' if any(k.startswith("AUTO_G16_LAUNCH_HANDOFF") for k in os.environ):g_fail()\n'),
 (41,
  41,
  '',
  '  pinned_carrier=g_parse(g_un64(carrier_pin),32768)\n'
  '  '
  'carrier_raw,carrier_stat=g_read_published(parent,G_CARRIER_PENDING,G_CARRIER,65536,fds);carrier_handles=tuple(fds[-2:])\n'
  '  c=g_carrier(carrier_raw);w=c["workspace"]\n'
  '  for k in ("attempt_id","workspace_binding_id"):\n'
  '   if c[k]!=constants[k]:g_fail()\n'
  '  if w["path"]!=constants["workspace"]:g_fail()\n'),
 (45,
  45,
  '',
  '  '
  'carrier_desc=g_file_desc(w["path"],c["handoff"]["parent_chain"],token,G_CARRIER,carrier_stat,carrier_raw)\n'
  '  if carrier_desc!=pinned_carrier:g_fail()\n'
  '  '
  'start_raw,start_stat=g_read_published(parent,G_QSUB_START_PENDING,G_QSUB_START,262144,fds);start_handles=tuple(fds[-2:])\n'
  '  start=g_parse(start_raw,262144)\n'
  '  '
  'entry_raw,entry_stat=g_read_published(parent,G_ENTRY_PENDING,G_ENTRY,16384,fds);entry_handles=tuple(fds[-2:])\n'
  '  '
  'entry_desc=g_file_desc(w["path"],c["handoff"]["parent_chain"],token,G_ENTRY,entry_stat,entry_raw)\n'
  '  '
  'g_validate_qsub_start(start,c,carrier_desc,entry_desc,g_template(w["path"],constants["resources"]))\n'
  '  def launch_evidence_check():\n'
  '   cwd_check()\n'
  '   for handles,names,expected in '
  '((carrier_handles,(G_CARRIER_PENDING,G_CARRIER),g_ident(carrier_stat)),(start_handles,(G_QSUB_START_PENDING,G_QSUB_START),g_ident(start_stat)),(entry_handles,(G_ENTRY_PENDING,G_ENTRY),g_ident(entry_stat))):\n'
  '    for handle,name in zip(handles,names):\n'
  '     current=os.fstat(handle);named=os.stat(name,dir_fd=parent,follow_symlinks=False)\n'
  '     if not stat.S_ISREG(current.st_mode) or current.st_uid!=os.getuid() or '
  'stat.S_IMODE(current.st_mode)!=384 or current.st_nlink!=2 or g_ident(current)!=expected or '
  'g_ident(named)!=expected:g_fail()\n'),
 (59,
  60,
  '   g_publish(parent,stem+".pending",stem+".json",data,cwd_check);stages.append(data)\n',
  '   g_publish(parent,stem+".pending",stem+".json",data,launch_evidence_check if not stages else '
  'cwd_check);stages.append(data)\n'),
 (61,
  62,
  '  entry,_=g_read(parent,G_NAMES[0],h["artifacts"]["entry"],token,fds)\n',
  '  entry_template,_=g_read(parent,G_NAMES[0],h["artifacts"]["entry"],token,fds)\n'
  '  if entry_raw!=g_render_entry(entry_template,carrier_desc):g_fail()\n'),
 (68,
  69,
  '  if material["schema"]!="v31-completion-rendering-material/6" or '
  'binding["binding_schema"]!="v31-completion-prebinding/7" or spec["program_kind"]!="gaussian" or '
  'type(spec["adapter_contract_version"]) is not int or '
  'spec["adapter_contract_version"]!=4:g_fail()\n',
  '  if material["schema"]!="v31-completion-rendering-material/7" or '
  'binding["binding_schema"]!="v31-completion-prebinding/8" or spec["program_kind"]!="gaussian" or '
  'type(spec["adapter_contract_version"]) is not int or '
  'spec["adapter_contract_version"]!=5:g_fail()\n'),
 (75,
  76,
  '  for role,name,form,data in '
  '(("scheduler-script",G_NAMES[0],"pbs-shell-utf8",entry),("startup-payload",G_NAMES[1],"canonical-json-utf8",payload)):\n',
  '  for role,name,form,data in '
  '(("scheduler-script",G_NAMES[0],"pbs-shell-utf8",entry_template),("startup-payload",G_NAMES[1],"canonical-json-utf8",payload)):\n'),
 (95,
  97,
  '  if len(sys.argv)!=2:g_fail()\n  g_loader(g_parse(g_un64(sys.argv[1]),8192))\n',
  '  if len(sys.argv)!=3:g_fail()\n  g_loader(g_parse(g_un64(sys.argv[1]),8192),sys.argv[2])\n'))
_LOADER_BODY = rewrite_lines_exact(
    _q5._LOADER_BODY,
    "3bce01a1af4d3e387ac977cd1ab78e89bce0e935f3ca5caba53c6ff4233ddf95",
    "165b811837f86d36cf39a56ae799a69ed8184454c679a97550b50539f90dffca",
    _LOADER_EDITS,
    "Gaussian file-carrier loader",
)
_DECODED_LOADER_SOURCE = PROTOCOL_SOURCE + "\n" + _LOADER_BODY
_LOADER_SOURCE = (
    "import base64,zlib\nexec(compile(zlib.decompress(base64.b64decode("
    + repr(base64.b64encode(zlib.compress(_DECODED_LOADER_SOURCE.encode(), 9)).decode())
    + ")), '<auto-g16-v31-gaussian-loader>', 'exec', dont_inherit=True, optimize=0))\n"
)


def _wrapper_sources():
    wrapper, probe = _q5._wrapper_sources()
    replacements = (
        ('material.get("schema")!="v31-completion-rendering-material/6" or binding.get("binding_schema")!="v31-completion-prebinding/7"',
         'material.get("schema")!="v31-completion-rendering-material/7" or binding.get("binding_schema")!="v31-completion-prebinding/8"'),
        ('payload["schema"]!="auto-g16-v31-publisher-qualification/5"',
         'payload["schema"]!="auto-g16-v31-publisher-qualification/6"'),
        ('spec["program_kind"]!="gaussian" or spec["adapter_contract_version"]!=4',
         'spec["program_kind"]!="gaussian" or spec["adapter_contract_version"]!=5'),
    )
    return rewrite_exact(wrapper, replacements, "Gaussian file-carrier wrapper"), probe


_envelope = _q5._envelope


def _payload(artifacts):
    ns = protocol_namespace()
    if len(artifacts) != 2:
        raise ExecutionValueError("Gaussian short entry requires two artifacts")
    for item, role, name, form, cap in zip(artifacts, ("scheduler-script", "startup-payload"), ("gaussian-entry-template.pbs", _PAYLOAD_NAME), ("pbs-shell-utf8", "canonical-json-utf8"), (16384, 8388608)):
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
    lines.append("exec "+" ".join(shlex.quote(x) for x in (py["path"],"-I","-S","-B","-c",_LOADER_SOURCE,base64.b64encode(_receipt_json(constants)).decode(),"__AUTO_G16_CARRIER_DESCRIPTOR_BASE64__")))
    entry=("\n".join(lines)+"\n").encode()
    if len(entry)>16384:raise ExecutionValueError("Gaussian entry exceeds 16 KiB")
    if entry.count(b"__AUTO_G16_CARRIER_DESCRIPTOR_BASE64__")!=1:raise ExecutionValueError("Gaussian carrier placeholder differs")
    result=tuple(freeze_mapping({"logical_role":role,"portable_name":name,"format":form,"sha256":sha256(data).hexdigest(),"size_bytes":len(data),"content_utf8":data.decode()},"Gaussian startup artifact") for role,name,form,data in (("scheduler-script","gaussian-entry-template.pbs","pbs-shell-utf8",entry),("startup-payload",_PAYLOAD_NAME,"canonical-json-utf8",raw)))
    _payload(result)
    return result


def _derived_artifacts(snapshot):
    """The only config/marker staging source, deterministically snapshot-owned."""
    from ._program_completion import _receipt_json
    if (snapshot.program_execution_spec.program_kind,snapshot.program_execution_spec.adapter_contract_version)!=("gaussian",5):return ()
    cfg=_payload(snapshot.scheduler_artifacts)["config_bytes"]
    marker=_receipt_json({"program_execution_snapshot_id":snapshot.program_execution_snapshot_id,"effect_intent_id":snapshot.effect_intent_id})
    return tuple(({"artifact_kind":role,"logical_role":role,"portable_name":name,"format":"canonical-json-utf8","sha256":sha256(raw).hexdigest(),"size_bytes":len(raw)},raw) for role,name,raw in (("derived-config","gaussian-config.json",cfg),("submit-intent-marker",".auto-g16-v31-submit-intent",marker)))


def _review_disclosure(snapshot):
    """Expanded review only: no extra snapshot identity or operational authority."""
    return {
        "schema": "auto-g16-v31-gaussian-startup-review/1",
        "physical_handoff_contract_sha256": _CONTRACT_SHA256,
        "derived_stages": [declaration for declaration, _ in _derived_artifacts(snapshot)],
        "artifact_caps": {"gaussian-entry-template.pbs": 16384, "gaussian.pbs": 16384, "gaussian-startup.json": 8388608, "gaussian-config.json": 6291456, ".auto-g16-v31-submit-intent": 65536},
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
            "predecessor_contract_sha256": _PREDECESSOR_CONTRACT_SHA256,
            "file_carrier_contract_sha256": _CONTRACT_SHA256,
            "carrier": {"pending": "v31-launch-carrier.pending", "final": "v31-launch-carrier.json", "maximum_bytes": 65536},
            "entry": {"template": "gaussian-entry-template.pbs", "pending": "gaussian.pbs.pending", "final": "gaussian.pbs", "maximum_bytes": 16384, "substitution": "canonical-carrier-descriptor-base64"},
            "qsub_invocation_start": {"pending": "v31-qsub-invocation-start.pending", "final": "v31-qsub-invocation-start.json", "maximum_bytes": 262144},
            "qsub_argv": "direct-d-l-q-script-without-v-or-V",
            "order": ["durable-stages", "handoff", "pre-authority", "file-carrier", "qsub-invocation-start", "single-qsub", "post-receipt"],
        },
    }
