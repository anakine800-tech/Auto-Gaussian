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
