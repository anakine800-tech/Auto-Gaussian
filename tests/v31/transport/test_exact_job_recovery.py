"""Real native owners/stores, inert final process peer; never a target call."""
import base64
import copy
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import sqlite3
import signal
import time
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from auto_g16 import core, execution
from auto_g16.execution import _submission_recovery as native
from auto_g16.transport import _submission_recovery as proof
from auto_g16.transport import _program_rtwin as rtwin, _driver, _bridge
from auto_g16.transport._recovery_process import _RecoveryProcessOwner
from auto_g16.transport._canonical import canonical_json_bytes, TransportBoundaryError
from scripts import run_v31_publisher_pilot as controller
from tests.v31.transport import test_publisher_collection_recovery as reuse
from tests.v31.transport import test_rtwin_successor_bridge as bridge
from auto_g16.execution import program_runtime as runtime
from auto_g16.transport import program as transport

HOST = {"machine_id_sha256": "a" * 64, "boot_id": "00000000-1111-2222-3333-444444444444"}


def qstat(expected):
    w = expected["workspace"]
    server, name = expected["server"], expected["scheduler_name"]
    number = expected["job_id"].split(".")[0]
    # Deliberately folded mid-path, never insert a space during reconstruction.
    fold = lambda s: s[:len(s)//2] + "\n\t" + s[len(s)//2:]
    fields = {"Job_Name": expected["scheduler_name"], "Job_Owner": expected["job_owner"], "euser": "user100",
        "job_state": "Q", "queue": "batch", "server": server, "init_work_dir": fold(w),
        "Output_Path": fold(server+":"+w+"/"+name+".o"+number), "Error_Path": fold(server+":"+w+"/"+name+".e"+number),
        "Resource_List.nodes": "1:ppn=8", "Resource_List.mem": "12288mb", "Resource_List.walltime": "01:00:00",
        "Variable_List": fold("PBS_O_INITDIR="+w+",PBS_O_WORKDIR="+w),
        "submit_args": fold("-d "+w+" -l nodes=1:ppn=8,mem=12288mb,walltime=3600 -q batch "+name)}
    return ("Job Id: "+expected["job_id"]+"\n"+"".join("    "+k+" = "+v+"\n" for k,v in fields.items())+"\n").encode()


def result(expected):
    before = {"host": HOST, "workspace_token": expected["workspace_token"], "marker": {"sha256": expected["marker_sha256"],
        "size_bytes": expected["marker_size"], "physical_token": "original-marker-token"}, "submitted": {"presence":"absent"}, "staged": expected["staged"]}
    return {"before": before, "after": copy.deepcopy(before), "scheduler": {"stdout_base64": base64.b64encode(qstat(expected)).decode(),
        "stderr_base64":"", "returncode":0, "completion_status":"completed", "eof_stdout":True,"eof_stderr":True}}


def framed(value):
    return _bridge._encode_frame({"protocol": _bridge._PROGRAM_BOOTSTRAP_PROTOCOL,"operation":"RECONCILE_SUBMISSION","status":"ok","result":value})


class RecoveryFixture(reuse._RecoveryFixture):
    def setUp(self):
        original_init = bridge._Wire.__init__
        def ambiguous(wire):
            original_init(wire);wire.fail_operation="SUBMIT_QSUB_ONCE"
        with patch.object(bridge._Wire,"__init__",ambiguous):
            super().setUp()
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.UNKNOWN)
        self.wire.fail_operation=None
        receipts=self.store.observations_for_attempt("attempt-1")
        def change(d):
            d["schema"]=proof.SCHEMA
            d["scope"].update(action="reconcile-exact-job-and-collect",maximum_reconciliation_epochs=1)
            d["scope"]["operations"]=["RECONCILE_SUBMISSION",*rtwin._COLLECTION_OPERATIONS]
            raw=proof.source_bytes()
            d["reconciliation"]={"submit_receipt_id":receipts[-1].observation_id,"job_owner":"user100@localhost","server":"server","host":HOST,"probe_source":{"sha256":sha256(raw).hexdigest(),"size_bytes":len(raw)},"prior_recovery_authority":None}
        self.installation=self.changed_installation(change)
        change(self.document)
        self.expected=proof.expected_evidence(self.snapshot,receipts,self.document)
        self.reply=result(self.expected)
        self.peer=self.wire.run
        def run(scope,invocation):
            if invocation.operation.name!="RECONCILE_SUBMISSION":return self.peer(scope,invocation)
            command,frame=rtwin._prepare_program_invocation(scope,invocation)
            request=_bridge._decode_frame(frame,cap=65536,field="fixture")
            self.wire.calls.append((invocation.operation.name,request))
            self.assertIn("snapshot_target",command[-1])
            self.assertNotIn('def exclusive_write',command[-1])
            return framed(self.reply),b"",0,"completed",True,True
        self.recovery_peer=run
        self.wire_patch.stop()
        self.wire_patch=patch.object(_driver._SubprocessRTWinDriver,"_run",side_effect=run)
        self.wire_patch.start();self.addCleanup(self.wire_patch.stop)
        self.recovery_patch=patch.object(_RecoveryProcessOwner,"_run",side_effect=run)
        self.recovery_patch.start();self.addCleanup(self.recovery_patch.stop)

    def reconcile(self):
        with patch.object(rtwin,"_FIXED_PUBLISHER_INSTALLATION",self.original),patch.object(rtwin,"_FIXED_COLLECTION_INSTALLATION",self.installation),patch.object(controller,"_FIXED_COLLECTION_RUN",self.run),patch.object(_driver.subprocess,"Popen",side_effect=AssertionError("no live process")):
            return controller._reconcile_fixed_publisher_submission()


class ExactRecoveryTests(RecoveryFixture):
    def test_concurrent_handle_and_process_reject_before_wire(self):
        with tempfile.TemporaryDirectory() as scratch:
            path=Path(scratch)/"state.json"
            self.export_state(path)
            state=json.loads(path.read_text());state["recovery_reply"]=self.reply;path.write_text(json.dumps(state))
            before=self.store.observations_for_attempt("attempt-1")
            with self.program_transport_store._completion_guard():
                with self.assertRaisesRegex(TransportBoundaryError,"busy"):self.reconcile()
                rejected=json.loads(_child("reconcile",path).stdout)
                self.assertIn("busy",rejected["rejected"]);self.assertEqual(rejected["wire_reads"],0)
            self.assertEqual(self.store.observations_for_attempt("attempt-1"),before)
            self.assertEqual(self.reconcile()["outcome"],"SUCCEEDED")

    def test_history_drift_retains_raw_without_promoting(self):
        def drift(scope,invocation):
            raw=self.recovery_peer(scope,invocation)
            self.store.append_observation(core.Observation(observation_id="concurrent-unrelated",attempt_id="attempt-1",observation_type="inert-external",data={"value":1}))
            return raw
        with patch.object(_RecoveryProcessOwner,"_run",side_effect=drift),self.assertRaisesRegex(TransportBoundaryError,"raw retained"):self.reconcile()
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.UNKNOWN)
        records=self.store.observations_for_attempt("attempt-1")
        self.assertEqual(records[-1].observation_type,proof.RAW)
        self.assertTrue(records[-1].data["raw"]["stdout_base64"])
        with self.assertRaisesRegex(TransportBoundaryError,"already consumed"):self.reconcile()
        self.assertEqual(len(self.wire.calls),1)

    def test_later_collection_continuation_pins_original_recovery_authority(self):
        self.reconcile()
        self.wire.scheduler = (0, b"Job Id: 123.server\n    job_state = Q\n", b"")
        self.assertNotEqual(self.resume().data["verdict"], "SUCCEEDED")
        original_authority = self.installation.continuation
        def update(d):
            d["reconciliation"]["prior_recovery_authority"] = {"sha256": original_authority.sha256, "size_bytes": original_authority.size_bytes}
        next_installation = self.changed_installation(update)
        next_installation = replace(next_installation, evidence=(*next_installation.evidence, original_authority))
        self.wire.scheduler = (153,b"",b"qstat: Unknown Job Id Error 123.server\n")
        self.wire.calls.clear()
        assessment = self.resume(installation=next_installation)
        self.assertEqual(assessment.data["verdict"],"SUCCEEDED")
        self.assertNotIn("RECONCILE_SUBMISSION", [op for op,_ in self.wire.calls])
        self.wire.calls.clear()
        self.assertEqual(self.resume(installation=next_installation),assessment)
        self.assertEqual(self.wire.calls,[])

    def test_wrong_job_completion_receipt_cannot_promote(self):
        self.reconcile()
        receipt=json.loads(self.wire.outputs["v31-completion.json"])
        receipt["job_id"]="124.server"
        self.wire.outputs["v31-completion.json"]=canonical_json_bytes(receipt)
        self.assertNotEqual(self.resume().data["verdict"],"SUCCEEDED")
        self.assertNotEqual(self.store.attempt_state("attempt-1"),core.AttemptState.SUCCEEDED)

    def test_native_unknown_reconcile_collect_replay_preserves_original_history(self):
        original=self.store.observations_for_attempt("attempt-1")
        outcome=tuple(self.store._connection.execute("SELECT * FROM submission_outcomes").fetchone())
        response=self.reconcile()
        self.assertEqual(response["outcome"],"SUCCEEDED")
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
        self.assertEqual(len(self.wire.calls),1)
        self.assertEqual(self.reconcile(),response)
        self.assertEqual(len(self.wire.calls),1)
        captured=self.resume()
        self.assertEqual(captured.data["verdict"],"SUCCEEDED")
        self.wire.calls.clear()
        self.assertEqual(self.resume(),captured);self.assertEqual(self.wire.calls,[])
        self.assertEqual(tuple(self.store._connection.execute("SELECT * FROM submission_outcomes").fetchone()),outcome)
        self.assertEqual(self.store.observations_for_attempt("attempt-1")[:4],original)

    def test_rejected_raw_persisted_unknown_no_second_wire(self):
        self.reply["after"]["host"]={**HOST,"boot_id":"different"}
        response=self.reconcile()
        self.assertEqual(response["outcome"],"UNKNOWN")
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.UNKNOWN)
        self.assertEqual(self.reconcile(),response);self.assertEqual(len(self.wire.calls),1)
        observations=self.store.observations_for_attempt("attempt-1")
        self.assertEqual([r.observation_type for r in observations[4:6]],[proof.START,proof.RAW])
        self.assertEqual(observations[5].data["raw"],response["raw"])

    def test_once_consumed_before_wire(self):
        append=core.SQLiteRuntimeStore.append_observation
        class Death(BaseException):pass
        def kill(store,record):
            append(store,record)
            if record.observation_type==proof.START:raise Death()
        with patch.object(core.SQLiteRuntimeStore,"append_observation",kill),self.assertRaises(Death):self.reconcile()
        with self.assertRaisesRegex(TransportBoundaryError,"already consumed"):self.reconcile()
        self.assertEqual(self.wire.calls,[])


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.expected={"job_id":"123.server","job_owner":"user100@localhost","server":"server","workspace":"/home/user100/SDL/inert-project/inert-attempt","scheduler_name":"xtb.pbs","resources":{"cores":8,"memory_mb":12288,"walltime_seconds":3600,"queue":"batch"}}

    def test_folded_and_negative_identity_fields(self):
        raw=qstat(self.expected)
        proof.scheduler_identity(raw,self.expected)
        for before,after in [(b"123.server",b"124.server"),(b"user100@localhost",b"other@localhost"),(b"euser = user100",b"euser = other"),(b"server = server",b"server = foreign"),(b"mem=12288",b"mem=12289"),(b"queue = batch",b"queue = other"),(b"01:00:00",b"01:00:01")]:
            with self.subTest(before=before),self.assertRaises(TransportBoundaryError):proof.scheduler_identity(raw.replace(before,after),self.expected)
        for bad in [raw+raw,raw.replace(b"    queue = batch",b"    queue = batch\n    queue = batch"),raw[:-1].rstrip(b"\n"),b"Job Id: 123.server\n\torphan\n"]:
            with self.subTest(raw=bad),self.assertRaises(TransportBoundaryError):proof.scheduler_identity(bad,self.expected)

    def test_raw_identity_and_ambiguity_matrix(self):
        expected={**self.expected,"host":HOST,"workspace_token":"workspace-token","marker_sha256":"a"*64,"marker_size":7,"staged":[{"portable_name":"seed.xyz","sha256":"b"*64,"size_bytes":4,"artifact_physical_token":"exact-token"}]}
        def raw(data):
            return {"stdout_base64":base64.b64encode(framed(data)).decode(),"stderr_base64":"","returncode":0,"completion_status":"completed","eof_stdout":True,"eof_stderr":True}
        valid=result(expected)
        self.assertEqual(proof.interpret(raw(valid),expected),"123.server")
        mutations=(lambda d:d["before"]["host"].update(boot_id="wrong"),
                   lambda d:d["before"].update(workspace_token="foreign"),
                   lambda d:d["before"]["marker"].update(sha256="c"*64),
                   lambda d:d["before"]["marker"].update(size_bytes=8),
                   lambda d:d["before"]["submitted"].update(presence="present"),
                   lambda d:d["before"]["staged"][0].update(artifact_physical_token="foreign"),
                   lambda d:d["scheduler"].update(returncode=153),
                   lambda d:d["scheduler"].update(stderr_base64=base64.b64encode(b"warning").decode()),
                   lambda d:d["scheduler"].update(eof_stdout=False),
                   lambda d:d["scheduler"].update(stdout_base64=""))
        for change in mutations:
            data=copy.deepcopy(valid);change(data)
            # Ensure negative preidentity cases cannot hide behind only the
            # before/after inequality check.
            data["after"]=copy.deepcopy(data["before"])
            with self.assertRaises(TransportBoundaryError):proof.interpret(raw(data),expected)
        for key,value in (("returncode",True),("completion_status","timeout"),("eof_stderr",False),("stdout_base64","invalid")):
            value_raw=raw(valid);value_raw[key]=value
            with self.assertRaises(TransportBoundaryError):proof.interpret(value_raw,expected)

    def test_probe_has_no_mutating_entrypoints_and_old_source_stable(self):
        import ast
        tree=ast.parse(proof.source_bytes())
        names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse(names & {"exclusive_write","project_observe","parent"})
        self.assertIn("snapshot_target",names)
        self.assertNotIn(b"server_qsub",proof.source_bytes())


class ProcessCaptureTests(unittest.TestCase):
    def observe_child(self,pid):
        self.assertIs(type(pid),int);self.assertGreater(pid,0);self.assertLessEqual(pid,0x7fffffff)
        if sys.platform=="darwin":
            import ctypes
            import errno
            # Darwin SDK: proc_bsdshortinfo, PROC_PIDT_SHORTBSDINFO=13, SZOMB=5.
            # Query the real kernel state without executing the setuid /bin/ps.
            class BsdShortInfo(ctypes.Structure):
                _fields_=[(name,ctypes.c_uint32) for name in ("pid","ppid","pgid","status")]+[
                    ("comm",ctypes.c_char*16)]+[(name,ctypes.c_uint32) for name in (
                    "flags","uid","gid","ruid","rgid","svuid","svgid","reserved")]
            self.assertEqual(ctypes.sizeof(BsdShortInfo),64)
            library=ctypes.CDLL("/usr/lib/libproc.dylib",use_errno=True)
            query=library.proc_pidinfo
            query.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int]
            query.restype=ctypes.c_int
            info=BsdShortInfo();ctypes.set_errno(0)
            size=query(pid,13,0,ctypes.byref(info),ctypes.sizeof(info));error=ctypes.get_errno()
            if size==0 and error==errno.ESRCH:return None
            if size<=0:raise OSError(error or errno.EIO,"proc_pidinfo observation failed")
            self.assertEqual(size,ctypes.sizeof(info),"incomplete process observation")
            self.assertEqual(info.pid,pid,"process observation identity mismatch")
            self.assertIn(info.status,(1,2,3,4,5),"unknown process state")
            return info.pid,info.pgid,"Z" if info.status==5 else str(info.status)
        observed=subprocess.run(["/bin/ps","-p",str(pid),"-o","pid=,pgid=,stat="],capture_output=True,text=True,timeout=2)
        if observed.returncode==1 and not observed.stdout.strip() and not observed.stderr.strip():return None
        self.assertEqual(observed.returncode,0,observed.stderr)
        fields=observed.stdout.split();self.assertEqual(len(fields),3)
        self.assertEqual(int(fields[0]),pid)
        return int(fields[0]),int(fields[1]),fields[2]

    def assert_child_exited(self,pid,group):
        # Darwin can report EPERM for a disappeared process group; observe the
        # exact self-created child instead of treating signal errors as proof.
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            observed=self.observe_child(pid)
            if observed is None:return
            self.assertEqual(observed[:2],(pid,group))
            if observed[2].startswith("Z"):return
            time.sleep(.01)
        self.fail("exact owned child survived leader-exit timeout: "+repr(observed))

    def test_process_observer_checks_real_live_identity_and_exit(self):
        process=subprocess.Popen([sys.executable,"-c","import sys; sys.stdin.buffer.read()"],stdin=subprocess.PIPE,start_new_session=True)
        try:
            observed=self.observe_child(process.pid)
            self.assertEqual(observed[:2],(process.pid,process.pid))
            self.assertFalse(observed[2].startswith("Z"))
            with self.assertRaises(AssertionError):self.assert_child_exited(process.pid,process.pid+1)
            with self.assertRaisesRegex(AssertionError,"survived leader-exit timeout"):
                self.assert_child_exited(process.pid,process.pid)
            process.communicate(timeout=2);self.assertEqual(process.returncode,0)
            self.assertIsNone(self.observe_child(process.pid))
            self.assert_child_exited(process.pid,process.pid)
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=2)
            if process.stdin is not None:process.stdin.close()

    def test_process_observer_denials_and_short_reads_cannot_prove_exit(self):
        import ctypes
        import errno
        for size,error in ((0,errno.EPERM),(0,errno.EACCES),(0,0),(-1,errno.ESRCH),(1,0),(63,0),(65,0)):
            with self.subTest(size=size,error=error):
                def rejected_query(*args):
                    ctypes.set_errno(error)
                    return size
                # Fault injection only: no simulated successful exit observation.
                with patch.object(sys,"platform","darwin"),patch.object(ctypes,"CDLL",return_value=SimpleNamespace(proc_pidinfo=rejected_query)):
                    with self.assertRaises(OSError if size<=0 else AssertionError):
                        self.assert_child_exited(os.getpid(),os.getpgrp())

    def test_timeout_kills_owned_group_after_leader_exit(self):
        source="import os,time\nif os.fork(): os._exit(0)\nos.write(1,str(os.getpid()).encode())\ntime.sleep(30)\n"
        process=subprocess.Popen([sys.executable,"-c",source],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            raw=_RecoveryProcessOwner()._communicate_bounded(process,b"",SimpleNamespace(timeout_seconds=.25,stdout_cap=32,stderr_cap=32))
            self.assertEqual(raw[3],"timeout");self.assertTrue(raw[0])
            self.assert_child_exited(int(raw[0]),process.pid)
        finally:
            try:os.killpg(process.pid,signal.SIGKILL)
            except (ProcessLookupError,PermissionError):pass

    def test_outer_partial_timeout_cap_and_eof(self):
        owner=_RecoveryProcessOwner()
        for source, cap, expected in [("import os,time;os.write(1,b'partial');time.sleep(10)",32,"timeout"),
                                      ("import os;os.write(1,b'x'*100)",32,"output-cap"),
                                      ("import os;os.write(1,b'complete')",32,"completed")]:
            with self.subTest(expected=expected):
                process=subprocess.Popen([sys.executable,"-c",source],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
                raw=owner._communicate_bounded(process,b"",SimpleNamespace(timeout_seconds=.25,stdout_cap=cap,stderr_cap=32))
                self.assertEqual(raw[3],expected)
                self.assertTrue(raw[0]);self.assertLessEqual(len(raw[0]),cap)

    def namespace(self):
        ns={"__name__":"inert_probe"}
        exec(compile(proof.source_bytes(),"recovery-probe","exec"),ns)
        return ns

    def test_probe_precheck_and_after_failure_preserve_query(self):
        ns=self.namespace()
        before={"host":HOST,"marker":{"sha256":"a"*64,"size_bytes":7},"submitted":{"presence":"absent"}}
        binding={"remote_workspace":"/inert","workspace_physical_token":"inert"}
        payload={"recovery_identity":{"host":HOST,"marker_sha256":"a"*64,"marker_size":7},"request_payload":{"observed_job_id":"123.server"}}
        calls=[]
        ns.update(snapshot_target=lambda *args:before,scheduler_capture=lambda *args:calls.append(True) or {"raw":"retained"})
        with tempfile.TemporaryDirectory() as folder:
            ns["named_directory"]=lambda *args:os.open(folder,os.O_RDONLY)
            changed=copy.deepcopy(payload);changed["recovery_identity"]["host"]={**HOST,"boot_id":"wrong"}
            self.assertIsNone(ns["observe_job"](binding,changed,{})["scheduler"]);self.assertEqual(calls,[])
            count=[]
            def observation(*args):
                if count:raise ValueError("post-query identity drift")
                count.append(True);return before
            ns["snapshot_target"]=observation
            result=ns["observe_job"](binding,payload,{})
            self.assertEqual(result["scheduler"],{"raw":"retained"});self.assertIsNone(result["after"])

    def test_probe_real_local_child_caps_and_post_executable_drift(self):
        ns=self.namespace()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/"qstat"
            for body,status in [("import os;os.write(1,b'x'*100000)","output-cap"),
                                ("import os;os.write(1,b'kept');open(__file__,'a').write('# drift')","transport-error"),
                                ("import os;os.write(1,b'exact')","completed")]:
                path.write_text("#!"+sys.executable+"\n"+body+"\n");path.chmod(0o700)
                raw=path.read_bytes();root={"path":str(path),"expected_size_bytes":len(raw),"expected_sha256":sha256(raw).hexdigest()}
                fd=os.open(folder,os.O_RDONLY);cwd=os.open(".",os.O_RDONLY)
                try:result=ns["scheduler_capture"](root,["-f","123.server"],fd)
                finally:os.fchdir(cwd);os.close(cwd);os.close(fd)
                self.assertEqual(result["completion_status"],status)
                self.assertTrue(base64.b64decode(result["stdout_base64"]))

    def test_probe_timeout_retains_raw_and_kills_exited_leader_group(self):
        ns=self.namespace()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/"qstat"
            path.write_text("#!"+sys.executable+"\nimport os,time\nif os.fork(): os._exit(0)\nos.write(1,(str(os.getpid())+':'+str(os.getpgrp())).encode())\ntime.sleep(30)\n");path.chmod(0o700)
            raw=path.read_bytes();root={"path":str(path),"expected_size_bytes":len(raw),"expected_sha256":sha256(raw).hexdigest()}
            fd=os.open(folder,os.O_RDONLY);cwd=os.open(".",os.O_RDONLY)
            try:result=ns["scheduler_capture"](root,["-f","123.server"],fd)
            finally:os.fchdir(cwd);os.close(cwd);os.close(fd)
            pid,group=map(int,base64.b64decode(result["stdout_base64"]).decode().split(':'))
            try:
                self.assertEqual(result["completion_status"],"timeout")
                self.assert_child_exited(pid,group)
            finally:
                try:os.killpg(group,signal.SIGKILL)
                except (ProcessLookupError,PermissionError):pass


def _process_entry(mode,path):
    if mode=="build":
        fixture=RecoveryFixture();fixture.setUp()
        fixture.export_state(path)
        state=json.loads(Path(path).read_text())
        state["recovery_reply"]=fixture.reply
        Path(path).write_text(json.dumps(state))
        os._exit(0)
    state=reuse._unpack(json.loads(Path(path).read_text()))
    wire=bridge._Wire();wire.outputs=state["outputs"]
    wire.scheduler=(153,b"",b"qstat: Unknown Job Id Error 123.server\n")
    phase=mode.removeprefix("crash-") if mode.startswith("crash-") else None
    count_path=Path(str(path)+".wire")
    def read_peer(scope,invocation):
        rtwin._prepare_program_invocation(scope,invocation)
        if phase=="before-wire":os._exit(17)
        with count_path.open("ab") as out:out.write(b"read\n");out.flush();os.fsync(out.fileno())
        if phase=="wire":os._exit(17)
        return framed(state["recovery_reply"]),b"",0,"completed",True,True
    with ExitStack() as stack:
        for module,name,value in ((rtwin,"_FIXED_PUBLISHER_INSTALLATION",state["original"]),
                                   (rtwin,"_FIXED_COLLECTION_INSTALLATION",state["installation"]),
                                   (controller,"_FIXED_COLLECTION_RUN",state["run"])):
            stack.enter_context(patch.object(module,name,value))
        stack.enter_context(patch.object(_RecoveryProcessOwner,"_run",side_effect=read_peer))
        stack.enter_context(patch.object(_driver._SubprocessRTWinDriver,"_run",side_effect=wire.run))
        stack.enter_context(patch.object(_driver.subprocess,"Popen",side_effect=AssertionError("no live process")))
        append=core.SQLiteRuntimeStore.append_observation
        effect=transport._ProgramTransportStore.record_effect
        disposition=core.SQLiteRuntimeStore.reconcile_unknown
        def observation(store,record):
            if phase=="before-start" and record.observation_type==proof.START:os._exit(17)
            if phase=="before-raw" and record.observation_type==proof.RAW:os._exit(17)
            append(store,record)
            if (phase=="start" and record.observation_type==proof.START) or (phase=="raw" and record.observation_type==proof.RAW) or (phase=="receipt" and record.observation_type==transport._RECEIPT_TYPE and record.data["operation"]=="RECONCILE_SUBMISSION"):os._exit(17)
        def recorded(store,**kwargs):
            value=effect(store,**kwargs)
            if phase=="effect" and kwargs["request"]["operation"]=="RECONCILE_SUBMISSION":os._exit(17)
            return value
        def transition(store,*args,**kwargs):
            value=disposition(store,*args,**kwargs)
            if phase=="disposition":os._exit(17)
            return value
        stack.enter_context(patch.object(core.SQLiteRuntimeStore,"append_observation",observation))
        stack.enter_context(patch.object(transport._ProgramTransportStore,"record_effect",recorded))
        stack.enter_context(patch.object(core.SQLiteRuntimeStore,"reconcile_unknown",transition))
        try:
            if mode=="collect":
                result=controller._resume_fixed_publisher_collection()
                outcome={"assessment":result.observation_id,"verdict":result.data["verdict"],"capture":result.data["capture_authority_id"],"result":result.data["evidence_result_id"]}
            else:
                response=controller._reconcile_fixed_publisher_submission()
                outcome={"outcome":response["outcome"]}
        except (TransportBoundaryError,execution.ExecutionValueError) as exc:outcome={"rejected":str(exc)}
        connection=sqlite3.connect(Path(state["run"].databases[0].path).as_uri()+"?mode=ro",uri=True)
        try:
            outcome["state"]=connection.execute("SELECT state FROM attempts").fetchone()[0]
            outcome["original_outcome"]=connection.execute("SELECT outcome FROM submission_outcomes").fetchone()[0]
            outcome["observations"]=connection.execute("SELECT observation_id,observation_type,data FROM observations ORDER BY sequence").fetchall()
            outcome["results"]=connection.execute("SELECT result_id,data FROM results ORDER BY sequence").fetchall()
        finally:connection.close()
        outcome["wire_reads"]=len(count_path.read_bytes().splitlines()) if count_path.exists() else 0
        outcome["collection_calls"]=len(wire.calls)
        print(json.dumps(outcome),flush=True)


def _child(mode,path,scratch=None):
    env=dict(os.environ)
    if scratch is not None:env["TMPDIR"]=str(scratch)
    result=subprocess.run([sys.executable,"-m","tests.v31.transport.test_exact_job_recovery",mode,str(path)],env=env,capture_output=True,text=True,timeout=180)
    if result.returncode not in {0,17}:raise AssertionError(result.stdout+result.stderr)
    return result


class FreshProcessTests(unittest.TestCase):
    def test_real_process_crash_boundaries_no_second_read(self):
        for phase in ("before-start","start","before-wire","wire","before-raw","raw","effect","receipt","disposition"):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as scratch:
                path=Path(scratch)/"state.json"
                _child("build",path,scratch)
                self.assertEqual(_child("crash-"+phase,path).returncode,17)
                after=json.loads(_child("reconcile",path).stdout)
                self.assertEqual(after["original_outcome"],"UNKNOWN")
                self.assertLessEqual(after["wire_reads"],1)
                if phase in {"before-start","receipt","disposition"}:
                    self.assertEqual(after["state"],"SUBMITTED");self.assertEqual(after["outcome"],"SUCCEEDED")
                else:
                    self.assertEqual(after["state"],"UNKNOWN");self.assertIn("rejected",after)
                again=json.loads(_child("reconcile",path).stdout)
                self.assertEqual(again,after)

    def test_fresh_process_restore_capture_terminal_replay(self):
        with tempfile.TemporaryDirectory() as scratch:
            path=Path(scratch)/"state.json"
            _child("build",path,scratch)
            recovered=json.loads(_child("reconcile",path).stdout)
            self.assertEqual(recovered["state"],"SUBMITTED")
            captured=json.loads(_child("collect",path).stdout)
            self.assertEqual(captured["verdict"],"SUCCEEDED")
            self.assertTrue(captured["capture"]);self.assertTrue(captured["result"])
            replay=json.loads(_child("collect",path).stdout)
            self.assertEqual(replay,{**captured,"collection_calls":0})
            self.assertEqual(replay["original_outcome"],"UNKNOWN");self.assertEqual(replay["wire_reads"],1)


if __name__=="__main__":
    if len(sys.argv)==3 and sys.argv[1] in {"build","reconcile","collect"} or len(sys.argv)==3 and sys.argv[1].startswith("crash-"):
        _process_entry(sys.argv[1],sys.argv[2])
    else:unittest.main()
