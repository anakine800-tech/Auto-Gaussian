"""Fixed Linux publisher source. Production receipt-mode activation remains blocked."""

_WRAPPER_SOURCE = r'''import base64,ctypes,datetime,hashlib,json,os,re,stat,subprocess,sys,time
DF=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0)
RF=os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_CLOEXEC",0)
PORTABLE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
CAP=64*1024*1024

class AbsentFile(FileNotFoundError):pass

def fail(reason): raise ValueError(reason)
def pairs(items):
    value={}
    for k,v in items:
        if k in value: fail("duplicate-field")
        value[k]=v
    return value
def canonical(v): return json.dumps(v,ensure_ascii=False,allow_nan=False,separators=(",",":"),sort_keys=True).encode("utf-8")+b"\n"
def closed(raw):
    v=json.loads(raw.decode("utf-8"),object_pairs_hook=pairs)
    if canonical(v)!=raw: fail("canonical-json")
    return v
def b64(raw): return base64.b64encode(raw).decode("ascii")
def un64(v):
    raw=base64.b64decode(v.encode("ascii"),validate=True)
    if b64(raw)!=v: fail("canonical-base64")
    return raw
def node(v):
    if v is None:return ["null",None]
    if type(v) is bool:return ["boolean",v]
    if type(v) is int:return ["integer",v]
    if type(v) is str:return ["string",v]
    if type(v) is list:return ["sequence",[node(x) for x in v]]
    if type(v) is dict:return ["mapping",[[k,node(v[k])] for k in sorted(v)]]
    fail("identity-type")
def semantic(v):return hashlib.sha256(json.dumps(node(v),ensure_ascii=False,separators=(",",":"),sort_keys=False).encode("utf-8")).hexdigest()
def identity(s):return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def pin_directory(path):
    if type(path) is not str or not path.startswith("/") or path!=os.path.normpath(path):fail("directory-path")
    parts=[] if path=="/" else path.split("/")[1:]
    if any(not x or x in {".",".."} for x in parts):fail("directory-path")
    fd=os.open("/",DF);fds=[fd];chain=[[os.fstat(fd).st_dev,os.fstat(fd).st_ino]]
    try:
        for part in parts:
            child=os.open(part,DF,dir_fd=fd);fds.append(child);fd=child
            s=os.fstat(fd);chain.append([s.st_dev,s.st_ino])
        return fd,b64(canonical(["v31-directory/1",path,chain])),fds
    except BaseException:
        for descriptor in reversed(fds):os.close(descriptor)
        raise

def directory(path):
    fd,token,fds=pin_directory(path)
    for parent in fds[:-1]:os.close(parent)
    return fd,token

def reattest_directory(path,token,fds):
    parts=[] if path=="/" else path.split("/")[1:]
    expected=closed(un64(token))[2]
    if len(fds)!=len(expected) or len(parts)+1!=len(fds):fail("workspace-chain")
    root=os.stat("/",follow_symlinks=False)
    if [root.st_dev,root.st_ino]!=expected[0]:fail("workspace-root")
    for i,fd in enumerate(fds):
        current=os.fstat(fd)
        if [current.st_dev,current.st_ino]!=expected[i]:fail("workspace-descriptor")
        if i:
            named=os.stat(parts[i-1],dir_fd=fds[i-1],follow_symlinks=False)
            if not stat.S_ISDIR(named.st_mode) or [named.st_dev,named.st_ino]!=expected[i]:fail("workspace-replaced")

def read_name(parent,name,limit=CAP,runtime=False):
    valid=re.fullmatch(r"[A-Za-z0-9._-]+",name) if runtime else PORTABLE.fullmatch(name)
    if name not in {".auto-g16-v31-submit-intent"} and (not valid or name in {".",".."}):fail("file-name")
    try:fd=os.open(name,RF,dir_fd=parent)
    except FileNotFoundError as exc:raise AbsentFile(name) from exc
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0<=before.st_size<=limit:fail("file-type-size")
        chunks=[];remaining=before.st_size
        while remaining:
            block=os.read(fd,min(remaining,1048576))
            if not block:fail("short-read")
            chunks.append(block);remaining-=len(block)
        named=os.stat(name,dir_fd=parent,follow_symlinks=False)
        if os.read(fd,1) or identity(before)!=identity(os.fstat(fd)) or identity(before)!=identity(named):fail("file-drift")
        return b"".join(chunks),identity(before)
    finally:os.close(fd)

def exclusive(parent,name,raw):
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
    try:
        offset=0
        while offset<len(raw):
            n=os.write(fd,raw[offset:])
            if n<=0:fail("short-write")
            offset+=n
        os.fsync(fd)
    finally:os.close(fd)

def file_identity(path,size,digest):
    prefix,name=path.rsplit("/",1);parent,token=directory(prefix or "/")
    try:
        raw,ident=read_name(parent,name, max(CAP,size),runtime=True)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=digest:fail("runtime-drift")
        return ident,token
    finally:os.close(parent)

def subreaper():
    if sys.platform!="linux":fail("unsupported-subreaper")
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:fail("subreaper-unavailable")
    value=ctypes.c_int()
    if libc.prctl(37,ctypes.byref(value),0,0,0)!=0 or value.value!=1:fail("subreaper-not-established")

def wait_all(pid,deadline):
    direct=None
    while True:
        try:child,status=os.waitpid(-1,os.WNOHANG)
        except ChildProcessError:
            if direct is None:fail("direct-status-missing")
            return direct
        if child==pid:direct=status
        if time.monotonic()>=deadline:fail("managed-writers-not-terminated")
        if child==0:time.sleep(0.01)

def publish(parent,workspace,token,raw,chain=None):
    if len(raw)>65536:fail("receipt-cap")
    if chain is not None:reattest_directory(workspace,token,chain)
    check,current=directory(workspace)
    try:
        if current!=token or identity(os.fstat(check))[:2]!=identity(os.fstat(parent))[:2]:fail("workspace-replaced")
    finally:os.close(check)
    exclusive(parent,"v31-completion.pending",raw)
    data,ident=read_name(parent,"v31-completion.pending",65536)
    if data!=raw:fail("receipt-write-drift")
    check,current=directory(workspace)
    try:
        if current!=token or identity(os.fstat(check))[:2]!=identity(os.fstat(parent))[:2]:fail("workspace-replaced")
        if read_name(parent,"v31-completion.pending",65536)!=(data,ident):fail("receipt-replaced")
        if chain is not None:reattest_directory(workspace,token,chain)
        os.link("v31-completion.pending","v31-completion.json",src_dir_fd=parent,dst_dir_fd=parent,follow_symlinks=False)
    finally:os.close(check)

def run(config):
    if set(config)!={"prebinding","prebinding_sha256","spec","material","xtb_data_path","cores","walltime_seconds"}:fail("config-shape")
    binding=config["prebinding"];spec=config["spec"];material=config["material"]
    if semantic(binding)!=config["prebinding_sha256"] or semantic(material)!=binding["rendering_material_sha256"]:fail("prebinding-drift")
    if spec["program_kind"]!="xtb" or spec["adapter_contract_version"]!=3 or spec["program_data"]["completion_mode"]!="receipt-on-absence-v1":fail("program-mode")
    if semantic(spec)!=binding["program_execution_spec_payload_sha256"] or spec["program_execution_spec_id"]!=binding["program_execution_spec_id"]:fail("spec-drift")
    roots=closed(un64(material["deployment_manifest_base64"]))["trust_roots"]
    python=roots["server_python"]
    if os.path.abspath(sys.executable)!=python["path"]:fail("python-path")
    py_identity=file_identity(python["path"],python["expected_size_bytes"],python["expected_sha256"])
    executable=spec["invocation"]["executable_identity"]
    exe_identity=file_identity(executable["absolute_path"],executable["size_bytes"],executable["sha256"])
    workspace=binding["cwd_binding"]["path"];parent,token,workspace_chain=pin_directory(workspace)
    logfd=None;execfd=None
    try:
        marker_raw,marker_identity=read_name(parent,".auto-g16-v31-submit-intent",65536)
        marker=closed(marker_raw)
        if set(marker)!={"program_execution_snapshot_id","effect_intent_id"} or any(type(x) is not str or not x for x in marker.values()):fail("submit-marker")
        job=os.environ.get("PBS_JOBID","")
        if not PORTABLE.fullmatch(job):fail("pbs-job-id")
        names=[x["portable_name"] for x in spec["exact_inputs"]+spec["required_outputs"]+spec["optional_outputs"]]
        reserved={"v31-completion.pending","v31-completion.json","v31-completion-launch.lock","xtb.pbs"}
        if len(names)!=len(set(names)) or set(names)&reserved:fail("name-collision")
        for name in ("v31-completion.pending","v31-completion.json",*[x["portable_name"] for x in spec["required_outputs"]+spec["optional_outputs"]]):
            try:os.stat(name,dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:pass
            else:fail("existing-output")
        reattest_directory(workspace,token,workspace_chain)
        exclusive(parent,"v31-completion-launch.lock",b"v31-completion-launch/1\n")
        inputs=[];input_identities=[]
        for declaration in spec["exact_inputs"]:
            raw,ident=read_name(parent,declaration["portable_name"])
            if len(raw)!=declaration["size_bytes"] or hashlib.sha256(raw).hexdigest()!=declaration["sha256"]:fail("input-drift")
            inputs.append(declaration);input_identities.append(ident)
        data_manifest=closed(un64(material["xtb_runtime_data_manifest_base64"]))
        data_identities=[]
        for name,item in sorted(data_manifest["files"].items()):
            data_identities.append((name,file_identity(config["xtb_data_path"]+"/"+name,item["size_bytes"],item["sha256"])))
        subreaper()
        log=next(x["portable_name"] for x in spec["required_outputs"] if x["logical_role"]=="program-log")
        reattest_directory(workspace,token,workspace_chain)
        logfd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        log_object=identity(os.fstat(logfd))[:2]
        execparent,exe_token=directory(executable["absolute_path"].rsplit("/",1)[0])
        try:execfd=os.open(executable["absolute_path"].rsplit("/",1)[1],RF,dir_fd=execparent)
        finally:os.close(execparent)
        if identity(os.fstat(execfd))!=exe_identity[0] or exe_token!=exe_identity[1]:fail("executable-replaced")
        os.fchdir(parent)
        env={"OMP_NUM_THREADS":str(config["cores"]),"XTBPATH":config["xtb_data_path"]}
        reattest_directory(workspace,token,workspace_chain)
        proc=subprocess.Popen(spec["invocation"]["argv"],executable="/proc/self/fd/"+str(execfd),pass_fds=(execfd,),stdin=subprocess.DEVNULL,stdout=logfd,stderr=logfd,env=env,shell=False)
        status=wait_all(proc.pid,time.monotonic()+config["walltime_seconds"])
        if os.WIFEXITED(status):term={"kind":"exited","returncode":os.WEXITSTATUS(status),"signal":None};code=term["returncode"]
        elif os.WIFSIGNALED(status):term={"kind":"signaled","returncode":None,"signal":os.WTERMSIG(status)};code=128+term["signal"]
        else:fail("direct-status-invalid")
        proc.returncode=code if term["kind"]=="exited" else -term["signal"]
        os.fsync(logfd)
        log_finished=identity(os.fstat(logfd))
        if log_finished[:2]!=log_object or identity(os.stat(log,dir_fd=parent,follow_symlinks=False))!=log_finished:fail("log-replaced")
        os.close(logfd);logfd=None
        if file_identity(python["path"],python["expected_size_bytes"],python["expected_sha256"])!=py_identity:fail("python-replaced")
        if file_identity(executable["absolute_path"],executable["size_bytes"],executable["sha256"])!=exe_identity:fail("executable-replaced")
        if read_name(parent,".auto-g16-v31-submit-intent",65536)!=(marker_raw,marker_identity):fail("marker-replaced")
        for declaration,ident in zip(inputs,input_identities):
            raw,current=read_name(parent,declaration["portable_name"])
            if current!=ident or hashlib.sha256(raw).hexdigest()!=declaration["sha256"]:fail("input-replaced")
        for name,ident in data_identities:
            item=data_manifest["files"][name]
            if file_identity(config["xtb_data_path"]+"/"+name,item["size_bytes"],item["sha256"])!=ident:fail("runtime-data-replaced")
        outputs=[]
        for declaration in spec["required_outputs"]+spec["optional_outputs"]:
            item={k:declaration[k] for k in ("logical_role","portable_name","format")}
            try:raw,ident=read_name(parent,declaration["portable_name"],declaration["max_size_bytes"])
            except AbsentFile:
                if declaration["portable_name"]==log:fail("log-disappeared")
                item.update(presence="absent",size_bytes=None,sha256=None)
            else:
                if declaration["portable_name"]==log and ident!=log_finished:fail("log-replaced")
                item.update(presence="present",size_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            outputs.append(item)
        receipt={"schema":"auto-g16-v31-program-completion/1","pre_execution_binding_sha256":config["prebinding_sha256"],"attempt_id":binding["attempt_id"],"program_execution_snapshot_id":marker["program_execution_snapshot_id"],"effect_intent_id":marker["effect_intent_id"],"job_id":job,"workspace_binding_id":binding["workspace_binding_id"],"remote_workspace":workspace,"workspace_physical_token":token,"program_execution_spec_id":spec["program_execution_spec_id"],"program_execution_spec_payload_sha256":binding["program_execution_spec_payload_sha256"],"program_kind":"xtb","adapter_id":spec["adapter_id"],"adapter_contract_version":3,"operation":spec["program_data"]["task"],"completion_mode":"receipt-on-absence-v1","wrapper_source_sha256":binding["wrapper_source_sha256"],"wrapper_source_size_bytes":binding["wrapper_source_size_bytes"],"submit_marker_sha256":hashlib.sha256(marker_raw).hexdigest(),"inputs":inputs,"outputs":outputs,"termination":term,"finished_at":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
        publish(parent,workspace,token,canonical(receipt),workspace_chain)
        return code
    finally:
        if logfd is not None:os.close(logfd)
        if execfd is not None:os.close(execfd)
        for descriptor in reversed(workspace_chain):os.close(descriptor)
if __name__=="__main__":
    try:code=run(closed(un64(sys.argv[1])))
    except BaseException:sys.exit(125)
    sys.exit(code)
'''

__all__: tuple[str, ...] = ()

# Independently selected source branch. Never change the historical source above.
# This fixed observation code is shared with the inert qualification probe; the
# probe reports facts only and cannot issue Q, approvals, or deployment authority.
_PUBLISHER_HOST_SOURCE = r'''
def system_bytes(path,cap):
    prefix,name=path.rsplit("/",1)
    parent,token,fds=pin_directory(prefix or "/")
    fd=None
    try:
        fd=os.open(name,RF,dir_fd=parent);before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):fail("host-file-type")
        blocks=[];size=0
        while True:
            block=os.read(fd,min(65536,cap+1-size))
            if not block:break
            blocks.append(block);size+=len(block)
            if size>cap:fail("host-file-cap")
        if identity(before)!=identity(os.fstat(fd)) or identity(before)!=identity(os.stat(name,dir_fd=parent,follow_symlinks=False)):fail("host-file-drift")
        reattest_directory(prefix or "/",token,fds)
        return b"".join(blocks)
    finally:
        if fd is not None:os.close(fd)
        for item in reversed(fds):os.close(item)

def host_node(s):return {"device":s.st_dev,"inode":s.st_ino}
def mount_unescape(value):
    if re.search(r"\\(?!040|011|012|134)",value):fail("mount-escape")
    return re.sub(r"\\(040|011|012|134)",lambda m:chr(int(m[1],8)),value)
def host_mounts():
    rows=[]
    for line in system_bytes("/proc/"+str(os.getpid())+"/mountinfo",4*1024*1024).decode("utf-8").splitlines():
        fields=line.split(" ")
        if fields.count("-")!=1:fail("mountinfo-shape")
        split=fields.index("-")
        if split<6 or len(fields)!=split+4:fail("mountinfo-shape")
        device=fields[2].split(":")
        if len(device)!=2 or any(re.fullmatch(r"0|[1-9][0-9]*",x) is None for x in [fields[0],*device]):fail("mountinfo-number")
        rows.append({"mount_id":int(fields[0]),"device_major":int(device[0]),"device_minor":int(device[1]),"root":mount_unescape(fields[3]),"mount_point":mount_unescape(fields[4]),"filesystem_type":mount_unescape(fields[split+1]),"source":mount_unescape(fields[split+2]),"mount_options":sorted(set(fields[5].split(","))),"super_options":sorted(set(fields[split+3].split(",")))})
    return rows

def host_location(role,path,mounts):
    parent_path=path.rsplit("/",1)[0] or "/"
    parent,token,fds=pin_directory(parent_path);fd=None
    try:
        if path=="/":fd=os.open("/",DF)
        else:fd=os.open(path.rsplit("/",1)[1],DF if role in {"workspace-root","xtb-data-root"} else RF,dir_fd=parent)
        obj=os.fstat(fd)
        if role not in {"workspace-root","xtb-data-root"} and not stat.S_ISREG(obj.st_mode):fail("host-runtime-type")
        named=os.stat(path.rsplit("/",1)[1],dir_fd=parent,follow_symlinks=False) if path!="/" else os.stat("/",follow_symlinks=False)
        if host_node(named)!=host_node(obj):fail("host-location-replaced")
        reattest_directory(parent_path,token,fds)
        matches=[m for m in mounts if m["mount_point"]=="/" or path==m["mount_point"] or path.startswith(m["mount_point"]+"/")]
        if not matches:fail("host-mount-missing")
        longest=max(len(m["mount_point"]) for m in matches)
        matches=[m for m in matches if len(m["mount_point"])==longest]
        if len(matches)!=1:fail("host-mount-ambiguous")
        mount=matches[0]
        if (os.major(obj.st_dev),os.minor(obj.st_dev))!=(mount["device_major"],mount["device_minor"]):fail("host-mount-device")
        return {"role":role,"path":path,"parent_chain":[host_node(os.fstat(x)) for x in fds],"object":host_node(obj),"mount":mount}
    finally:
        if fd is not None:os.close(fd)
        for item in reversed(fds):os.close(item)

def observe_publisher_host(runtime,remote_root,data_root):
    if sys.platform!="linux":fail("host-platform")
    machine=hashlib.sha256(system_bytes("/etc/machine-id",4096)).hexdigest()
    boot=system_bytes("/proc/sys/kernel/random/boot_id",128).decode("ascii")
    if boot.endswith("\n"):boot=boot[:-1]
    if re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}",boot) is None:fail("host-boot")
    uname=os.uname();mounts=host_mounts()
    # These two kernel procfs handles are the sole intentional symlink follows.
    namespaces={"mount":host_node(os.stat("/proc/self/ns/mnt")),"pid":host_node(os.stat("/proc/self/ns/pid"))}
    locations=[host_location(role,path,mounts) for role,path in zip(("workspace-root","server-python","xtb","xtb-data-root"),(remote_root,runtime["server_python"]["path"],runtime["xtb"]["path"],data_root))]
    for key in ("server_python","xtb"):
        entry=runtime[key];file_identity(entry["path"],entry["size_bytes"],entry["sha256"])
    return {"host_key":semantic({"machine_id_sha256":machine}),"machine_id_sha256":machine,"boot_id":boot,"kernel_release":uname.release,"architecture":uname.machine,"namespaces":namespaces,"locations":locations}

def publisher_host_guard(config):
    material=config["material"];binding=config["prebinding"]
    if material.get("schema")!="v31-completion-rendering-material/2" or binding.get("binding_schema")!="v31-completion-prebinding/3":fail("publisher-tuple")
    raw=un64(material["publisher_qualification_base64"])
    if len(raw)>1024*1024:fail("qualification-cap")
    q=closed(raw)
    if set(q)!={"payload","payload_sha256"} or semantic(q["payload"])!=q["payload_sha256"]:fail("qualification-digest")
    payload=q["payload"]
    if payload["schema"]!="auto-g16-v31-publisher-qualification/1":fail("qualification-schema")
    source=payload["implementation"]["wrapper_source"]
    if source!={"sha256":binding["wrapper_source_sha256"],"size_bytes":binding["wrapper_source_size_bytes"]}:fail("publisher-source")
    hosts=payload["hosts"]
    keys=[h["host_key"] for h in hosts]
    if not 1<=len(hosts)<=32 or keys!=sorted(set(keys)) or keys!=payload["execution_domain"]["eligible_host_keys"]:fail("publisher-host-set")
    actual=observe_publisher_host(payload["runtime"],payload["execution_domain"]["remote_root"],config["xtb_data_path"])
    matches=[h for h in hosts if h["host_key"]==actual["host_key"]]
    if len(matches)!=1:fail("publisher-host-unknown")
    expected=matches[0]
    for key in ("host_key","machine_id_sha256","boot_id","kernel_release","architecture","namespaces"):
        if actual[key]!=expected[key]:fail("publisher-host-"+key)
    if actual["locations"]!=[{k:v for k,v in loc.items() if k!="evidence"} for loc in expected["locations"]]:fail("publisher-host-locations")
    return actual
'''

# Source composition is deterministic at import, from source-controlled literals.
# The result is a separate complete script, not an artifact-selected extension.
_PUBLISHER_WRAPPER_SOURCE = _WRAPPER_SOURCE.replace(
    'def run(config):\n', _PUBLISHER_HOST_SOURCE + '\ndef run(config):\n', 1,
).replace(
    '    workspace=binding["cwd_binding"]["path"];',
    '    launch_host=publisher_host_guard(config)\n    workspace=binding["cwd_binding"]["path"];', 1,
).replace(
    '        proc=subprocess.Popen(',
    '        if publisher_host_guard(config)!=launch_host:fail("publisher-host-before-child")\n        proc=subprocess.Popen(', 1,
).replace(
    '        publish(parent,workspace,token,canonical(receipt),workspace_chain)',
    '        if publisher_host_guard(config)!=launch_host:fail("publisher-host-before-publication")\n        publish(parent,workspace,token,canonical(receipt),workspace_chain)', 1,
)
_PUBLISHER_PROBE_SOURCE = _WRAPPER_SOURCE.split('def run(config):\n', 1)[0] + _PUBLISHER_HOST_SOURCE + r'''
if __name__=="__main__":
    request=closed(un64(sys.argv[1]))
    if set(request)!={"runtime","remote_root","xtb_data_path"}:fail("probe-shape")
    print(canonical(observe_publisher_host(request["runtime"],request["remote_root"],request["xtb_data_path"])).decode("utf-8"),end="")
'''

_PUBLISHER_WRAPPER_SOURCE = _PUBLISHER_WRAPPER_SOURCE.replace(
    '    try:code=run(closed(un64(sys.argv[1])))',
    '    try:\n        raw=sys.stdin.buffer.read(8*1024*1024+2)\n        if len(sys.argv)!=1 or not raw.endswith(b"\\n") or len(raw)>8*1024*1024+1:fail("publisher-stdin-cap")\n        code=run(closed(un64(raw[:-1].decode("ascii"))))', 1,
)

# The final actual-host check is adjacent to the atomic link, after pending
# bytes have been fsynced/closed and re-read, not merely before pending creation.
_PUBLISHER_WRAPPER_SOURCE = _PUBLISHER_WRAPPER_SOURCE.replace(
    'def publish(parent,workspace,token,raw,chain=None):',
    'def publish(parent,workspace,token,raw,chain=None,config=None,launch_host=None):', 1,
).replace(
    '        os.link("v31-completion.pending","v31-completion.json",',
    '        if publisher_host_guard(config)!=launch_host:fail("publisher-host-before-publication")\n        os.link("v31-completion.pending","v31-completion.json",', 1,
).replace(
    '        if publisher_host_guard(config)!=launch_host:fail("publisher-host-before-publication")\n        publish(parent,workspace,token,canonical(receipt),workspace_chain)',
    '        publish(parent,workspace,token,canonical(receipt),workspace_chain,config,launch_host)', 1,
)
