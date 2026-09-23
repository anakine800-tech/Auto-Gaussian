"""Closed CREST startup payload tuple; no caller-provided executable loader."""
from __future__ import annotations

from hashlib import sha256
import base64
import json
import shlex

from ._identity import ExecutionValueError, freeze_mapping

_MATERIAL_SCHEMA = "v31-completion-rendering-material/4"
_Q_SCHEMA = "auto-g16-v31-publisher-qualification/3"
_Q_NAME = "v31-crest-publisher-qualification-v3.json"
_CONTRACT_SHA256 = "a80ffd756ac90b98740823cd902c4ecacfb0b661af4db757dacc3cc1e17d215c"
_PAYLOAD_SCHEMA = "auto-g16-v31-crest-startup-payload/1"
_PAYLOAD_NAME = "crest-startup.json"
_HEADER = "# auto-g16-v31-scheduler/5"

# Python 3.6 compatible. This stays in the publisher process: no extra child,
# shell, wait owner, signal handler, file-based config reload or fallback.
_LOADER_SOURCE = r'''
import os,sys,stat,json,base64,hashlib,io,builtins
DF=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
RF=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK
fds=[]
def fail():raise ValueError("crest-startup-integrity")
def pairs(items):
 d={}
 for k,v in items:
  if k in d:fail()
  d[k]=v
 return d
def canonical(v):return (json.dumps(v,ensure_ascii=False,allow_nan=False,separators=(",",":"),sort_keys=True)+"\n").encode()
def closed(raw):
 v=json.loads(raw.decode("utf-8"),object_pairs_hook=pairs)
 if canonical(v)!=raw:fail()
 return v
def un64(v):
 raw=base64.b64decode(v,validate=True)
 if base64.b64encode(raw).decode()!=v:fail()
 return raw
def identity(s):return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def path_parts(path):
 if type(path) is not str or not path.startswith("/") or path!=os.path.normpath(path):fail()
 parts=path.split("/")[1:]
 if not parts or any(not p or p in (".","..") for p in parts):fail()
 return parts
def walk(path):
 chain=[os.open("/",DF)]
 try:
  for p in path_parts(path):chain.append(os.open(p,DF,dir_fd=chain[-1]))
  return chain
 except BaseException:
  for fd in reversed(chain):os.close(fd)
  raise
def read(parent,name,size,digest,mode=None,owner=None):
 if type(size) is not int or not 0<size<=8*1024*1024 or type(digest) is not str or len(digest)!=64:fail()
 fd=os.open(name,RF,dir_fd=parent)
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode) or before.st_size!=size:fail()
  if mode is not None and stat.S_IMODE(before.st_mode)!=mode:fail()
  if owner is not None and before.st_uid!=owner:fail()
  raw=b""
  while len(raw)<=size:
   chunk=os.read(fd,min(8192,size+1-len(raw)))
   if not chunk:break
   raw+=chunk
  if identity(before)!=identity(os.fstat(fd)) or len(raw)!=size or hashlib.sha256(raw).hexdigest()!=digest:fail()
  named=os.stat(name,dir_fd=parent,follow_symlinks=False)
  if not stat.S_ISREG(named.st_mode) or identity(named)!=identity(before):fail()
  return raw
 finally:os.close(fd)
def reattest(parts,nodes):
 if [os.stat("/",follow_symlinks=False).st_dev,os.stat("/",follow_symlinks=False).st_ino]!=nodes[0]:fail()
 for i,fd in enumerate(fds):
  s=os.fstat(fd)
  if [s.st_dev,s.st_ino]!=nodes[i]:fail()
  if i:
   named=os.stat(parts[i-1],dir_fd=fds[i-1],follow_symlinks=False)
   if not stat.S_ISDIR(named.st_mode) or [named.st_dev,named.st_ino]!=nodes[i]:fail()
try:
 if len(sys.argv)!=2 or len(sys.argv[1])>16384:fail()
 v=closed(un64(sys.argv[1]))
 if set(v)!={"schema","workspace","project_token","payload_name","payload_sha256","payload_size_bytes","server_python"} or v["schema"]!="auto-g16-v31-crest-startup-invocation/1" or v["payload_name"]!="crest-startup.json":fail()
 py=v["server_python"]
 if set(py)!={"path","sha256","size_bytes"} or os.path.abspath(sys.executable)!=py["path"]:fail()
 py_parts=path_parts(py["path"]);pyfds=walk(py["path"].rsplit("/",1)[0])
 try:read(pyfds[-1],py_parts[-1],py["size_bytes"],py["sha256"])
 finally:
  for fd in reversed(pyfds):os.close(fd)
 parts=path_parts(v["workspace"])
 token=closed(un64(v["project_token"]))
 if not isinstance(token,list) or len(token)!=3 or token[:2]!=["v31-directory/1",v["workspace"].rsplit("/",1)[0]]:fail()
 if not isinstance(token[2],list) or len(token[2])!=len(parts):fail()
 if any(not isinstance(n,list) or len(n)!=2 or any(type(x) is not int or x<0 for x in n) for n in token[2]):fail()
 fds=walk(v["workspace"]);nodes=[[os.fstat(f).st_dev,os.fstat(f).st_ino] for f in fds]
 if nodes[:-1]!=token[2]:fail()
 ws=os.fstat(fds[-1])
 if ws.st_uid!=os.getuid() or stat.S_IMODE(ws.st_mode)!=0o700:fail()
 raw=read(fds[-1],v["payload_name"],v["payload_size_bytes"],v["payload_sha256"],0o600,os.getuid())
 payload=closed(raw)
 if set(payload)!={"schema","wrapper_source","config"} or payload["schema"]!="auto-g16-v31-crest-startup-payload/1":fail()
 source=payload["wrapper_source"]
 if type(source) is not str or not 0<len(source.encode())<=65536:fail()
 config=payload["config"]
 if not isinstance(config,dict) or set(config)!={"prebinding","prebinding_sha256","spec","material","xtb_data_path","cores","walltime_seconds"}:fail()
 cfg=canonical(config)
 if len(cfg)>6*1024*1024:fail()
 encoded=base64.b64encode(cfg)+b"\n"
 if len(encoded)>8*1024*1024+1:fail()
 material=config["material"];binding=config["prebinding"]
 if material.get("schema")!="v31-completion-rendering-material/4" or binding.get("binding_schema")!="v31-completion-prebinding/5":fail()
 q=closed(un64(material["publisher_qualification_base64"]))["payload"]
 digest={"sha256":hashlib.sha256(source.encode()).hexdigest(),"size_bytes":len(source.encode())}
 if q["schema"]!="auto-g16-v31-publisher-qualification/3" or q["implementation"]["wrapper_source"]!=digest:fail()
 if digest!={"sha256":binding["wrapper_source_sha256"],"size_bytes":binding["wrapper_source_size_bytes"]} or binding["cwd_binding"]!={"location_kind":"server","path":v["workspace"]}:fail()
 if binding["attempt_id"]!=parts[-1]:fail()
 reattest(parts,nodes)
 os.fchdir(fds[-1])
 if os.getcwd()!=v["workspace"]:fail()
 sys.argv=[sys.argv[0]]
 sys.stdin=io.TextIOWrapper(io.BytesIO(encoded),encoding="ascii")
 exec(compile(source,"<auto-g16-crest-publisher>","exec"),{"__name__":"__main__","__file__":"<auto-g16-crest-publisher>","__builtins__":builtins.__dict__})
finally:
 for fd in reversed(fds):os.close(fd)
'''.lstrip()


def _wrapper_sources():
    from ._crest_completion import _wrapper_sources as predecessor
    result = []
    for source in predecessor():
        for old, new in (("v31-completion-rendering-material/3", _MATERIAL_SCHEMA),
                         ("v31-completion-prebinding/4", "v31-completion-prebinding/5"),
                         ("auto-g16-v31-publisher-qualification/2", _Q_SCHEMA)):
            if source.count(old) != 1:
                raise ExecutionValueError("short-entry predecessor tuple drift")
            source = source.replace(old, new, 1)
        if '"crest.pbs"' in source:
            if source.count('"crest.pbs"') != 1:
                raise ExecutionValueError("short-entry reserved-name drift")
            source = source.replace('"crest.pbs"', '"crest.pbs","crest-startup.json"', 1)
        result.append(source)
    return tuple(result)


def _payload(artifacts):
    from ._program_completion import _canonical_json_object, _receipt_json
    if len(artifacts) != 2:
        raise ExecutionValueError("short entry requires its exact two artifacts")
    for item, role, name, form in zip(artifacts, ("scheduler-script", "startup-payload"), ("crest.pbs", _PAYLOAD_NAME), ("pbs-shell-utf8", "json")):
        if set(item) != {"logical_role", "portable_name", "format", "sha256", "size_bytes", "content_utf8"} or (item["logical_role"], item["portable_name"], item["format"]) != (role, name, form):
            raise ExecutionValueError("short-entry artifact inventory differs")
        raw = item["content_utf8"].encode()
        if len(raw) != item["size_bytes"] or sha256(raw).hexdigest() != item["sha256"]:
            raise ExecutionValueError("short-entry artifact digest differs")
    value = _canonical_json_object(artifacts[1]["content_utf8"].encode(), 8*1024*1024)
    if set(value) != {"schema", "wrapper_source", "config"} or value["schema"] != _PAYLOAD_SCHEMA or value["wrapper_source"] != _wrapper_sources()[0]:
        raise ExecutionValueError("short-entry payload source differs")
    if _receipt_json(value) != artifacts[1]["content_utf8"].encode():
        raise ExecutionValueError("noncanonical startup payload")
    return value


def _render(config, deployment, resources, project_binding):
    from ._program_completion import _receipt_json
    fields = config["prebinding"]
    from .project_provisioning import ProjectPhysicalBinding
    if type(project_binding) is not ProjectPhysicalBinding:
        raise ExecutionValueError("short entry requires closed native Project binding")
    project_binding.assert_identity_closed()
    if project_binding.project_physical_binding_id != fields["project_physical_binding_id"]:
        raise ExecutionValueError("short-entry Project binding differs")
    workspace = fields["cwd_binding"]["path"]
    if workspace != project_binding.remote_project_dir + "/" + fields["attempt_id"]:
        raise ExecutionValueError("short entry outside exact Project")
    token = project_binding.project_physical_identity
    try:
        parsed = json.loads(base64.b64decode(token, validate=True))
        if (type(parsed) is not list or len(parsed) != 3 or parsed[:2] != ["v31-directory/1", project_binding.remote_project_dir]
                or type(parsed[2]) is not list or len(parsed[2]) != len(project_binding.remote_project_dir.split("/"))
                or any(type(node) is not list or len(node) != 2 or any(type(x) is not int or x < 0 for x in node) for node in parsed[2])
                or base64.b64encode(_receipt_json(parsed)).decode() != token):
            raise ValueError("Project token")
    except (ValueError, TypeError) as exc:
        raise ExecutionValueError("short entry requires physical Project token") from exc
    if any(item["portable_name"] == _PAYLOAD_NAME for group in ("exact_inputs", "required_outputs", "optional_outputs") for item in config["spec"][group]):
        raise ExecutionValueError("startup payload name collides with program artifact")
    wrapper = _wrapper_sources()[0]
    cfg = _receipt_json(config)
    if len(wrapper.encode()) > 65536 or len(cfg) > 6*1024*1024 or len(base64.b64encode(cfg)) > 8*1024*1024:
        raise ExecutionValueError("short-entry wrapper/config cap")
    raw = _receipt_json({"schema": _PAYLOAD_SCHEMA, "wrapper_source": wrapper, "config": config})
    if len(raw) > 8*1024*1024:
        raise ExecutionValueError("startup payload cap")
    py = deployment["trust_roots"]["server_python"]
    invocation = {"schema": "auto-g16-v31-crest-startup-invocation/1", "workspace": workspace,
                  "project_token": token, "payload_name": _PAYLOAD_NAME,
                  "payload_sha256": sha256(raw).hexdigest(), "payload_size_bytes": len(raw),
                  "server_python": {"path": py["path"], "sha256": py["expected_sha256"], "size_bytes": py["expected_size_bytes"]}}
    lines = ["#!/bin/bash", _HEADER, f"#PBS -l nodes=1:ppn={resources.cores}", f"#PBS -l mem={resources.memory_mb}mb", f"#PBS -l walltime={resources.walltime_seconds}"]
    if resources.queue is not None:
        lines.append(f"#PBS -q {resources.queue}")
    lines.append("exec " + " ".join(shlex.quote(x) for x in (py["path"], "-I", "-S", "-B", "-c", _LOADER_SOURCE, base64.b64encode(_receipt_json(invocation)).decode())))
    script = ("\n".join(lines)+"\n").encode()
    if len(script) > 16384:
        raise ExecutionValueError("short PBS entry cap")
    return tuple(freeze_mapping({"logical_role": role, "portable_name": name, "format": form, "sha256": sha256(data).hexdigest(), "size_bytes": len(data), "content_utf8": data.decode()}, "startup artifact") for role, name, form, data in (("scheduler-script", "crest.pbs", "pbs-shell-utf8", script), ("startup-payload", _PAYLOAD_NAME, "json", raw)))
