"""Exact observed-job reconciliation: closed data and a read-only probe.

Old producer/bootstrap/operation bytes are intentionally not changed. The new
source is qualified only by a separately installed recovery continuation.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import re

from ._canonical import TransportBoundaryError, canonical_json_bytes

SCHEMA = "auto-g16-v31-exact-job-recovery-continuation/1"
REQUEST = "v31-exact-observed-job-reconciliation-request/1"
PROOF = "v31-exact-observed-job-reconciliation-proof/1"
START = "v31-exact-job-recovery-start/1"
RAW = "v31-exact-job-recovery-raw/1"
WIRE_CAP = 262144


def require(ok, message):
    if not ok:
        raise TransportBoundaryError("exact-job recovery: " + message)


def closed(value, keys):
    require(isinstance(value, dict) or hasattr(value, "keys"), "mapping required")
    require(set(value) == set(keys), "closed keys differ")
    return value


def un64(value, cap):
    require(type(value) is str and len(value) <= 4 * ((cap + 2) // 3), "raw cap")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise TransportBoundaryError("exact-job recovery: base64") from exc
    require(len(raw) <= cap and base64.b64encode(raw).decode() == value, "canonical raw")
    return raw


def scheduler_fields(raw, job_id):
    """Torque folds only with TAB, with no semantic whitespace invention."""
    require(type(raw) is bytes and len(raw) <= WIRE_CAP, "qstat cap")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise TransportBoundaryError("exact-job recovery: qstat encoding") from exc
    require(text.endswith("\n") and "\r" not in text and "\0" not in text, "qstat framing")
    lines = text[:-1].split("\n")
    if lines[-1] == "":
        lines.pop()
    require(lines and lines.pop(0) == "Job Id: " + job_id, "exact job header")
    fields = {}
    previous = None
    for line in lines:
        if line.startswith("\t"):
            require(previous is not None and re.fullmatch(r"\t[^\x00-\x1f\x7f]*", line) is not None, "bad continuation")
            require(re.match(r"\t\s*(?:[A-Za-z_][A-Za-z0-9_.-]*\s+=|Job Id:)", line) is None, "injected field")
            fields[previous] += line[1:]
        else:
            match = re.fullmatch(r"    ([A-Za-z_][A-Za-z0-9_.-]*) = ([^\x00-\x1f\x7f]+)", line)
            require(match is not None and match[1] not in fields, "invalid/duplicate field")
            previous = match[1]
            fields[previous] = match[2]
    return fields


def scheduler_identity(raw, expected):
    f = scheduler_fields(raw, expected["job_id"])
    workspace = expected["workspace"]
    resources = expected["resources"]
    seconds = resources["walltime_seconds"]
    wall = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    names = {"Job_Owner": expected["job_owner"], "euser": expected["job_owner"].split("@", 1)[0], "server": expected["server"], "queue": resources["queue"],
             "init_work_dir": workspace, "Resource_List.nodes": "1:ppn=" + str(resources["cores"]),
             "Resource_List.mem": str(resources["memory_mb"]) + "mb", "Resource_List.walltime": wall,
             "Job_Name": expected["scheduler_name"]}
    require(all(f.get(k) == v for k, v in names.items()), "scheduler identity mismatch")
    require(f.get("job_state") in {"Q", "W", "R", "B", "H", "S", "E", "T", "C", "F", "X"}, "job state")
    job_number = expected["job_id"].split(".", 1)[0]
    for key, suffix in (("Output_Path", ".o"), ("Error_Path", ".e")):
        require(f.get(key) == expected["server"] + ":" + workspace + "/" + expected["scheduler_name"] + suffix + job_number, "scheduler output path")
    variables = {}
    for entry in f.get("Variable_List", "").split(","):
        require("=" in entry, "variable record")
        key, value = entry.split("=", 1)
        require(key not in variables, "duplicate variable")
        variables[key] = value
    require(all(variables.get(k) == workspace for k in ("PBS_O_WORKDIR", "PBS_O_INITDIR")), "environment workspace")
    args = f"-d {workspace} -l nodes=1:ppn={resources['cores']},mem={resources['memory_mb']}mb,walltime={seconds} -q {resources['queue']} {expected['scheduler_name']}"
    require(f.get("submit_args") == args, "exact submission arguments")
    return f


def expected_evidence(snapshot, receipts, document):
    recovery = document["reconciliation"]
    workspace = [r for r in receipts if r.data["operation"] == "ALLOCATE_WORKSPACE" and r.data["outcome"] == "SUCCEEDED"]
    stages = [r for r in receipts if r.data["operation"] == "STAGE_EXACT_FILE" and r.data["outcome"] == "SUCCEEDED"]
    require(len(workspace) == 1 and len(stages) == len(snapshot.program_execution_spec.exact_inputs) + 1, "original stage inventory")
    marker = canonical_json_bytes({"program_execution_snapshot_id": snapshot.program_execution_snapshot_id, "effect_intent_id": snapshot.effect_intent_id})
    return {"job_id": document["original"]["job_id"], "job_owner": recovery["job_owner"], "server": recovery["server"],
            "host": dict(recovery["host"]), "workspace": snapshot.workspace_binding.remote_attempt_dir,
            "workspace_token": workspace[0].data["response"]["workspace_physical_token"],
            "marker_sha256": sha256(marker).hexdigest(), "marker_size": len(marker),
            "staged": [dict(r.data["response"]) for r in stages],
            "resources": {k: getattr(snapshot.resolved_resource_request, k) for k in ("cores", "memory_mb", "walltime_seconds", "queue")},
            "scheduler_name": snapshot.scheduler_artifacts[0]["portable_name"]}


def interpret(raw, expected):
    """Caller persists raw before calling. Any rejected identity remains UNKNOWN."""
    from . import _bridge
    closed(raw, {"stdout_base64", "stderr_base64", "returncode", "completion_status", "eof_stdout", "eof_stderr"})
    stdout = un64(raw["stdout_base64"], WIRE_CAP)
    stderr = un64(raw["stderr_base64"], 65536)
    require(type(raw["returncode"]) is int and raw["returncode"] == 0 and not stderr and raw["completion_status"] == "completed"
            and raw["eof_stdout"] is True and raw["eof_stderr"] is True, "ambiguous transport")
    message = _bridge._decode_frame(stdout, cap=WIRE_CAP, field="exact-job recovery response")
    closed(message, {"protocol", "operation", "status", "result"})
    require(message["protocol"] == _bridge._PROGRAM_BOOTSTRAP_PROTOCOL and message["operation"] == "RECONCILE_SUBMISSION" and message["status"] == "ok", "wire identity")
    data = closed(message["result"], {"before", "after", "scheduler"})
    before = closed(data["before"], {"host", "workspace_token", "marker", "submitted", "staged"})
    require(data["after"] == before, "target identity changed across query")
    require(before["host"] == expected["host"] and before["workspace_token"] == expected["workspace_token"], "host/workspace identity")
    marker = closed(before["marker"], {"sha256", "size_bytes", "physical_token"})
    require(marker["sha256"] == expected["marker_sha256"] and marker["size_bytes"] == expected["marker_size"], "intent marker")
    require(type(marker["physical_token"]) is str and marker["physical_token"], "marker token")
    require(before["submitted"] == {"presence": "absent"}, "submitted marker is not absent")
    require(tuple(before["staged"]) == tuple(expected["staged"]), "staged bytes or identity")
    qstat = closed(data["scheduler"], {"stdout_base64", "stderr_base64", "returncode", "completion_status", "eof_stdout", "eof_stderr"})
    require(type(qstat["returncode"]) is int and qstat["returncode"] == 0 and qstat["completion_status"] == "completed"
            and qstat["eof_stdout"] is True and qstat["eof_stderr"] is True and not un64(qstat["stderr_base64"], 65536), "ambiguous qstat")
    scheduler_identity(un64(qstat["stdout_base64"], 131072), expected)
    return expected["job_id"]


def source_bytes():
    """Extract only unchanged read helpers; no producer source is rewritten."""
    from ._bridge import _PROGRAM_BOOTSTRAP_SOURCE
    source = _PROGRAM_BOOTSTRAP_SOURCE
    # Retain original audited helpers without mutation-capable functions/main.
    parts = [source[:source.index("OPS=")], source[source.index("ENV="):source.index("def parent(")],
             source[source.index("def read_file("):source.index("def exclusive_write(")]]
    return ("".join(parts) + _PROBE).encode()


_PROBE = r'''
def snapshot_target(b,p):
    prefix=b["project_directory"].rsplit("/",1)[0]
    checks=[]
    try:
        checks.append(named_directory(prefix,b["parent_physical_identity"]))
        checks.append(named_directory(b["project_directory"],b["project_physical_identity"]))
        fd=named_directory(b["remote_workspace"],b["workspace_physical_token"]);checks.append(fd)
        with open("/etc/machine-id","rb") as f: machine=f.read(128)
        with open("/proc/sys/kernel/random/boot_id","r") as f: boot=f.read(128).strip()
        host={"machine_id_sha256":hashlib.sha256(machine).hexdigest(),"boot_id":boot}
        marker,data=attest_file(fd,b["workspace_physical_token"],".auto-g16-v31-submit-intent")
        try: os.stat(".auto-g16-v31-submitted",dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError: submitted={"presence":"absent"}
        else: submitted={"presence":"present"}
        stages=[]
        for item in p["staged"]:
            token,raw=attest_file(fd,b["workspace_physical_token"],item["portable_name"],item["artifact_physical_token"],item["sha256"])
            if len(raw)!=item["size_bytes"]: fail("staged-size")
            stages.append(dict(item,artifact_physical_token=token))
        # Reclose every ancestor/name before returning this observation.
        for path,token in ((prefix,b["parent_physical_identity"]),(b["project_directory"],b["project_physical_identity"]),(b["remote_workspace"],b["workspace_physical_token"])):
            check=named_directory(path,token);os.close(check)
        return {"host":host,"workspace_token":b["workspace_physical_token"],"marker":{"sha256":hashlib.sha256(data).hexdigest(),"size_bytes":len(data),"physical_token":marker},"submitted":submitted,"staged":stages}
    finally:
        for fd in reversed(checks):os.close(fd)
def scheduler_capture(root,args,fd):
    outputs={"out":bytearray(),"err":bytearray()};eof={"out":False,"err":False}
    status="transport-error";code=None;proc=None;selector=selectors.DefaultSelector()
    try:
        executable(trust(root));os.fchdir(fd)
        proc=subprocess.Popen([root["path"]]+args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=ENV,shell=False,start_new_session=True)
        deadline=time.monotonic()+10
        for key,stream in (("out",proc.stdout),("err",proc.stderr)):
            os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ,key)
        while selector.get_map():
            remaining=deadline-time.monotonic()
            if remaining<=0:status="timeout";break
            ready=selector.select(remaining)
            if not ready:status="timeout";break
            for key,_ in ready:
                limit=98304 if key.data=="out" else 32768
                data=os.read(key.fileobj.fileno(),min(65536,limit+1-len(outputs[key.data])))
                if not data:eof[key.data]=True;selector.unregister(key.fileobj);continue
                outputs[key.data].extend(data)
                if len(outputs[key.data])>limit:
                    del outputs[key.data][limit:];status="output-cap";raise ValueError("output-cap")
        else:
            try:code=proc.wait(timeout=max(.001,deadline-time.monotonic()));status="completed"
            except subprocess.TimeoutExpired:status="timeout"
        executable(trust(root))
    except (OSError,ValueError):
        if status!="output-cap":status="transport-error"
    finally:
        selector.close()
        if proc is not None:
            if status!="completed" or proc.poll() is None:
                import signal
                try:os.killpg(proc.pid,signal.SIGKILL)
                except OSError:proc.kill()
                proc.wait()
            proc.stdout.close();proc.stderr.close()
    return {"stdout_base64":b64(bytes(outputs["out"])),"stderr_base64":b64(bytes(outputs["err"])),"returncode":code,"completion_status":status,"eof_stdout":eof["out"],"eof_stderr":eof["err"]}
def observe_job(b,p,root):
    result={"before":None,"after":None,"scheduler":None}
    try:
        result["before"]=before=snapshot_target(b,p)
        expected=p["recovery_identity"];keys(expected,{"host","marker_sha256","marker_size"})
        if before["host"]!=expected["host"] or before["marker"]["sha256"]!=expected["marker_sha256"] or before["marker"]["size_bytes"]!=expected["marker_size"] or before["submitted"]!={"presence":"absent"}:return result
        fd=named_directory(b["remote_workspace"],b["workspace_physical_token"])
        try:result["scheduler"]=scheduler_capture(root,["-f",p["request_payload"]["observed_job_id"]],fd)
        finally:os.close(fd)
        result["after"]=snapshot_target(b,p)
    except (OSError,ValueError):pass
    return result
def main():
    deployment=closed(un64(sys.argv[1]));roots=deployment["trust_roots"]
    for key in ("server_python","server_qstat"):executable(trust(roots[key]))
    if os.path.abspath(sys.executable)!=roots["server_python"]["path"]:fail("python-path")
    head=sys.stdin.buffer.read(12)
    if len(head)!=12 or head[:4]!=MAGIC:fail("frame")
    size=struct.unpack(">Q",head[4:])[0]
    if size>65524:fail("frame-cap")
    raw=sys.stdin.buffer.read(size)
    if len(raw)!=size or sys.stdin.buffer.read(1):fail("frame-length")
    request=closed(raw);keys(request,{"protocol","operation","binding","payload"})
    if request["protocol"]!=PROTOCOL or request["operation"]!="RECONCILE_SUBMISSION":fail("operation")
    b=request["binding"];p=request["payload"];keys(p,{"request_payload","executable","resources","staged","recovery_identity"})
    original=p["request_payload"];keys(original,{"schema","submit_receipt_id","observed_job_id","continuation_sha256"})
    if original["schema"]!="v31-exact-observed-job-reconciliation-request/1" or not PORTABLE.fullmatch(original["observed_job_id"]):fail("request")
    if not b["remote_workspace"].startswith(ROOT+"/") or b["remote_workspace"]!=b["project_directory"]+"/"+b["attempt_id"]:fail("workspace")
    return respond("RECONCILE_SUBMISSION",observe_job(b,p,roots["server_qstat"]))
if __name__=="__main__":main()
'''
