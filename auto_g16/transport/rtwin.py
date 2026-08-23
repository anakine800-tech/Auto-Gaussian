"""RTwin-first execution/read adapters over the closed Transport protocol."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Callable, Final, Mapping

from auto_g16.execution import ConfirmedNoEffectError, EffectKind, EffectState, ExecutionSnapshot, PossiblyEffectfulError, RemoteEffectReceipt, ServerProfile

from ._canonical import TransportBoundaryError, canonical_bytes, strict_canonical_json
from ._driver import _BOOTSTRAP_PROTOCOL, _DeploymentAuthority, _FetchResult, _Invocation, _RTWinDriver, _SubprocessRTWinDriver, _TextResult, _is_fetch_result_closed, _is_text_result_closed, _operation, _resolve_deployment_authority
from .models import MAX_FETCH_ARTIFACT_BYTES, MAX_FETCH_CAPTURE_BYTES, ExactArtifactRequest, ExactRemoteJobBinding, FetchedArtifact, FetchedOutputCapture, SchedulerReadEvidence, TransportStore, _assert_binding_matches_snapshot, _validate_requests

_JOB_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_QSTAT_FIELD: Final = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_.-]*) = (.+)$")

def _utc_now()->str: return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
def _b64(value:bytes)->str: return base64.b64encode(value).decode("ascii")

def _base_binding(snapshot:ExecutionSnapshot,runtime:Mapping[str,object])->dict[str,object]:
    return {"transport_store_id":runtime["transport_store_id"],"store_instance_id":runtime["store_instance_id"],"runtime_attestation_id":runtime["runtime_attestation_id"],"attempt_id":snapshot.attempt_id,"execution_snapshot_id":snapshot.execution_snapshot_id,"submission_intent_id":snapshot.submission_intent_id,"remote_workspace":snapshot.workspace_binding.remote_attempt_dir}
def _workspace_binding(snapshot:ExecutionSnapshot,runtime:Mapping[str,object],workspace:Mapping[str,object])->dict[str,object]:
    return {**_base_binding(snapshot,runtime),"workspace_authority_id":workspace["workspace_authority_id"],"workspace_physical_token_base64":_b64(workspace["workspace_physical_token"])}
def _request(operation:str,binding:Mapping[str,object],payload:Mapping[str,object])->dict[str,object]: return {"binding":dict(binding),"operation":operation,"payload":dict(payload),"protocol":_BOOTSTRAP_PROTOCOL}
def _result_object(result:_TextResult)->Mapping[str,object]:
    if not _is_text_result_closed(result) or result.completion_status!="completed" or result.returncode!=0 or result.stderr or not result.eof_stdout or not result.eof_stderr: raise TransportBoundaryError("closed operation did not return an accepted result")
    value=strict_canonical_json(result.stdout,"operation result")
    if not isinstance(value,dict): raise TransportBoundaryError("operation result is not an object")
    return value

def _effect_kind(name:str)->EffectKind:
    return {"ALLOCATE_WORKSPACE":EffectKind.REMOTE_WORKSPACE,"STAGE_EXACT_FILE":EffectKind.INPUT_TRANSFER,"SUBMIT_QSUB_ONCE":EffectKind.SUBMISSION}.get(name,EffectKind.SUBMISSION_RECONCILIATION)
def _invoke_text(driver:_RTWinDriver,snapshot:ExecutionSnapshot,invocation:_Invocation)->_TextResult:
    try: result=driver.invoke_text(snapshot,invocation)
    except TransportBoundaryError as exc: raise ConfirmedNoEffectError(_effect_kind(invocation.operation.name),f"rtwin-{invocation.operation.token}-preflight-failed") from exc
    except Exception as exc: raise PossiblyEffectfulError(_effect_kind(invocation.operation.name),f"rtwin-{invocation.operation.token}-driver-error") from exc
    if not _is_text_result_closed(result): raise PossiblyEffectfulError(_effect_kind(invocation.operation.name),f"rtwin-{invocation.operation.token}-malformed-result")
    return result

def _qstat_classification(binding:ExactRemoteJobBinding,result:_TextResult)->tuple[str,str,str,int]:
    if not _is_text_result_closed(result) or len(result.stdout)>262144 or len(result.stderr)>65536:
        result=_TextResult(stdout=b"",stderr=b"",returncode=None,eof_stdout=False,eof_stderr=False,completion_status="transport-error")
    evidence=canonical_bytes([result.stdout,result.stderr,result.returncode,result.eof_stdout,result.eof_stderr,result.completion_status]); digest=sha256(evidence).hexdigest(); size=len(result.stdout)+len(result.stderr)
    if result.completion_status!="completed" or not result.eof_stdout or not result.eof_stderr: return "unknown","unknown",digest,size
    if result.returncode==153 and result.stdout==b"" and result.stderr==f"qstat: Unknown Job Id {binding.job_id}\n".encode("ascii"): return "absent","fresh",digest,size
    if result.returncode!=0 or result.stderr or b"\x00" in result.stdout or b"\r" in result.stdout: return "unknown","unknown",digest,size
    try: text=result.stdout.decode("utf-8")
    except UnicodeDecodeError: return "unknown","unknown",digest,size
    if not text.endswith("\n") or text.endswith("\n\n"): return "unknown","unknown",digest,size
    lines=text[:-1].split("\n")
    if not lines or lines[0]!=f"Job Id: {binding.job_id}" or len(lines)<2: return "unknown","unknown",digest,size
    fields={}
    for line in lines[1:]:
        match=_QSTAT_FIELD.fullmatch(line)
        if match is None or match.group(1) in fields: return "unknown","unknown",digest,size
        fields[match.group(1)]=match.group(2)
    state=fields.get("job_state")
    if not isinstance(state,str) or len(state)!=1 or not state.isascii() or not state.isupper(): return "unknown","unknown",digest,size
    return {"Q":"queued","W":"queued","R":"running","B":"running","H":"held","S":"held","E":"exiting","T":"exiting","C":"terminal","F":"terminal","X":"terminal"}.get(state,"unknown"),"fresh",digest,size

class RTWinExecutionAdapter:
    def __init__(self,*,transport_store:TransportStore,current_profile:ServerProfile)->None:
        if not isinstance(transport_store,TransportStore) or not isinstance(current_profile,ServerProfile): raise TransportBoundaryError("execution adapter dependencies are invalid")
        self._store=transport_store; self._profile=current_profile; self._driver:_RTWinDriver=_SubprocessRTWinDriver()
    @classmethod
    def _from_driver(cls,driver:_RTWinDriver,*,transport_store:TransportStore,current_profile:ServerProfile)->RTWinExecutionAdapter:
        value=cls(transport_store=transport_store,current_profile=current_profile); value._driver=driver; return value
    @property
    def contract_version(self)->str:return "rtwin-pbs-v1"
    def _authority(self,snapshot:ExecutionSnapshot)->tuple[_DeploymentAuthority,dict[str,object]]:
        authority=_resolve_deployment_authority(snapshot,self._profile); return authority,self._store._runtime(snapshot,authority)
    def allocate_attempt_workspace(self,snapshot:ExecutionSnapshot)->str:
        authority,runtime=self._authority(snapshot); operation=_operation("ALLOCATE_WORKSPACE"); binding=_base_binding(snapshot,runtime)
        invocation=_Invocation(operation=operation,argv=(),cwd=snapshot.workspace_binding.remote_attempt_dir,request=_request(operation.name,binding,{}),authority=authority)
        try: result=_result_object(_invoke_text(self._driver,snapshot,invocation)); token=base64.b64decode(result["workspace_physical_token_base64"],validate=True)
        except ConfirmedNoEffectError: raise
        except Exception as exc: raise PossiblyEffectfulError(EffectKind.REMOTE_WORKSPACE,"remote-workspace-outcome-ambiguous") from exc
        if result.get("remote_workspace")!=snapshot.workspace_binding.remote_attempt_dir: raise PossiblyEffectfulError(EffectKind.REMOTE_WORKSPACE,"remote-workspace-binding-drift")
        try:self._store._record_workspace(snapshot,runtime["runtime_attestation_id"],token)
        except Exception as exc: raise PossiblyEffectfulError(EffectKind.REMOTE_WORKSPACE,"remote-workspace-attestation-not-durable") from exc
        return snapshot.workspace_binding.remote_attempt_dir
    def transfer_exact_bytes(self,snapshot:ExecutionSnapshot,prepared_input_bytes:bytes,pbs_template_bytes:bytes)->None:
        authority,runtime=self._authority(snapshot)
        try:snapshot.prepared_input_binding.verify_bytes(prepared_input_bytes);snapshot.pbs_template_binding.verify_bytes(pbs_template_bytes);workspace=self._store._workspace(snapshot)
        except Exception as exc: raise ConfirmedNoEffectError(EffectKind.INPUT_TRANSFER,"exact staged authority is unavailable") from exc
        for kind,bound,content in (("prepared-input",snapshot.prepared_input_binding,prepared_input_bytes),("pbs-template",snapshot.pbs_template_binding,pbs_template_bytes)):
            operation=_operation("STAGE_EXACT_FILE"); binding=_workspace_binding(snapshot,runtime,workspace); payload={"artifact_kind":kind,"logical_name":bound.logical_name,"remote_relative_name":bound.logical_name,"sha256":bound.sha256,"size_bytes":bound.size_bytes,"content_base64":_b64(content)}
            invocation=_Invocation(operation=operation,argv=(bound.logical_name,bound.sha256,str(bound.size_bytes)),cwd=snapshot.workspace_binding.remote_attempt_dir,request=_request(operation.name,binding,payload),authority=authority)
            try: result=_result_object(_invoke_text(self._driver,snapshot,invocation)); token=base64.b64decode(result["artifact_physical_token_base64"],validate=True)
            except Exception as exc: raise PossiblyEffectfulError(EffectKind.INPUT_TRANSFER,"input-transfer-outcome-ambiguous") from exc
            if any(result.get(name)!=payload[name] for name in ("artifact_kind","logical_name","remote_relative_name","sha256","size_bytes")): raise PossiblyEffectfulError(EffectKind.INPUT_TRANSFER,"staged-artifact-binding-drift")
            try:self._store._record_artifact(snapshot,runtime["runtime_attestation_id"],workspace["workspace_authority_id"],kind=kind,logical_name=bound.logical_name,digest=bound.sha256,size=bound.size_bytes,token=token)
            except Exception as exc: raise PossiblyEffectfulError(EffectKind.INPUT_TRANSFER,"staged-artifact-attestation-not-durable") from exc
    def submit_once(self,snapshot:ExecutionSnapshot)->str:
        authority,runtime=self._authority(snapshot)
        try:
            workspace=self._store._workspace(snapshot); prepared=self._store._artifact(workspace["workspace_authority_id"],"prepared-input"); pbs=self._store._artifact(workspace["workspace_authority_id"],"pbs-template")
        except Exception as exc: raise ConfirmedNoEffectError(EffectKind.SUBMISSION,"exact staged authority is unavailable") from exc
        binding={**_workspace_binding(snapshot,runtime,workspace),"prepared_input_artifact_authority_id":prepared["artifact_authority_id"],"prepared_input_artifact_physical_token_base64":_b64(prepared["artifact_physical_token"]),"pbs_template_artifact_authority_id":pbs["artifact_authority_id"],"pbs_template_artifact_physical_token_base64":_b64(pbs["artifact_physical_token"])}
        operation=_operation("SUBMIT_QSUB_ONCE"); invocation=_Invocation(operation=operation,argv=(snapshot.pbs_template_binding.logical_name,),cwd=snapshot.workspace_binding.remote_attempt_dir,request=_request(operation.name,binding,{"pbs_basename":snapshot.pbs_template_binding.logical_name}),authority=authority)
        try: result=_result_object(_invoke_text(self._driver,snapshot,invocation)); job=result["job_id"]
        except Exception as exc: raise PossiblyEffectfulError(EffectKind.SUBMISSION,"qsub-outcome-ambiguous") from exc
        if not isinstance(job,str) or _JOB_ID.fullmatch(job) is None: raise PossiblyEffectfulError(EffectKind.SUBMISSION,"qsub-job-id-invalid")
        try:self._store._record_job(snapshot,runtime["runtime_attestation_id"],workspace["workspace_authority_id"],job)
        except Exception as exc: raise PossiblyEffectfulError(EffectKind.SUBMISSION,"qsub-job-authority-not-durable") from exc
        return job
    def reconcile_submission(self,snapshot:ExecutionSnapshot,*,effect_sequence:int)->RemoteEffectReceipt:
        authority,runtime=self._authority(snapshot)
        if type(effect_sequence) is not int or effect_sequence<1: raise TransportBoundaryError("effect_sequence must be positive")
        try: job=self._store._job(snapshot); workspace=self._store._workspace(snapshot); prepared=self._store._artifact(workspace["workspace_authority_id"],"prepared-input"); pbs=self._store._artifact(workspace["workspace_authority_id"],"pbs-template")
        except TransportBoundaryError:
            return RemoteEffectReceipt(attempt_id=snapshot.attempt_id,execution_snapshot_id=snapshot.execution_snapshot_id,submission_intent_id=snapshot.submission_intent_id,effect_sequence=effect_sequence,effect_kind=EffectKind.SUBMISSION_RECONCILIATION,effect_state=EffectState.POSSIBLY_EFFECTFUL,remote_workspace=snapshot.workspace_binding.remote_attempt_dir,details={"source":"rtwin-reconcile","status":"no-exact-job"})
        binding={**_workspace_binding(snapshot,runtime,workspace),"prepared_input_artifact_authority_id":prepared["artifact_authority_id"],"prepared_input_artifact_physical_token_base64":_b64(prepared["artifact_physical_token"]),"pbs_template_artifact_authority_id":pbs["artifact_authority_id"],"pbs_template_artifact_physical_token_base64":_b64(pbs["artifact_physical_token"])}
        operation=_operation("RECONCILE_SUBMISSION"); invocation=_Invocation(operation=operation,argv=(),cwd=snapshot.workspace_binding.remote_attempt_dir,request=_request(operation.name,binding,{"effect_sequence":effect_sequence}),authority=authority)
        try: result=_result_object(self._driver.invoke_text(snapshot,invocation))
        except Exception: result={"effect_state":"possibly_effectful"}
        state=result.get("effect_state"); confirmed=state=="confirmed_effect" and isinstance(result.get("job_id"),str) and result["job_id"]==job["job_id"]
        return RemoteEffectReceipt(attempt_id=snapshot.attempt_id,execution_snapshot_id=snapshot.execution_snapshot_id,submission_intent_id=snapshot.submission_intent_id,effect_sequence=effect_sequence,effect_kind=EffectKind.SUBMISSION_RECONCILIATION,effect_state=EffectState.CONFIRMED_EFFECT if confirmed else EffectState.POSSIBLY_EFFECTFUL,remote_workspace=snapshot.workspace_binding.remote_attempt_dir,job_id=job["job_id"] if confirmed else None,details={"source":"rtwin-reconcile","status":state if isinstance(state,str) else "possibly_effectful"})

class RTWinReadAdapter:
    def __init__(self,*,transport_store:TransportStore)->None:
        if not isinstance(transport_store,TransportStore): raise TransportBoundaryError("read adapter requires TransportStore")
        self._store=transport_store; self._driver:_RTWinDriver=_SubprocessRTWinDriver(); self._clock:Callable[[],str]=_utc_now
    @classmethod
    def _from_driver(cls,driver:_RTWinDriver,*,transport_store:TransportStore,clock:Callable[[],str]=_utc_now)->RTWinReadAdapter:
        value=cls(transport_store=transport_store); value._driver=driver; value._clock=clock; return value
    def _closed(self,snapshot:ExecutionSnapshot,binding:ExactRemoteJobBinding,current_profile:ServerProfile)->tuple[_DeploymentAuthority,dict[str,object],dict[str,object]]:
        _assert_binding_matches_snapshot(snapshot,binding,current_profile)
        if binding.transport_store_id!=self._store.transport_store_id or binding.store_instance_id!=self._store.store_instance_id: raise TransportBoundaryError("binding belongs to another TransportStore")
        receipt=self._store._receipt(snapshot,binding.remote_effect_receipt_id); authority=_resolve_deployment_authority(snapshot,current_profile); runtime=self._store._runtime(snapshot,authority)
        if receipt["job_id"]!=binding.job_id: raise TransportBoundaryError("binding differs from durable job")
        return authority,runtime,receipt
    def read_scheduler(self,snapshot:ExecutionSnapshot,binding:ExactRemoteJobBinding,current_profile:ServerProfile)->SchedulerReadEvidence:
        authority,runtime,receipt=self._closed(snapshot,binding,current_profile); workspace=self._store._workspace(snapshot)
        closed={**_workspace_binding(snapshot,runtime,workspace),"job_authority_id":receipt["job_authority_id"],"receipt_binding_id":receipt["receipt_binding_id"],"remote_effect_receipt_id":binding.remote_effect_receipt_id,"job_id":binding.job_id}
        operation=_operation("QUERY_SCHEDULER"); invocation=_Invocation(operation=operation,argv=("-f",binding.job_id),cwd=binding.remote_workspace,request=_request(operation.name,closed,{"job_id":binding.job_id}),authority=authority)
        try: result=self._driver.invoke_text(snapshot,invocation)
        except Exception: result=_TextResult(stdout=b"",stderr=b"",returncode=None,eof_stdout=False,eof_stderr=False,completion_status="transport-error")
        state,freshness,digest,size=_qstat_classification(binding,result)
        return SchedulerReadEvidence._from_classified(binding=binding,observed_at_utc=self._clock(),freshness=freshness,state=state,evidence_sha256=digest,evidence_size_bytes=size)
    def fetch_exact_output(self,snapshot:ExecutionSnapshot,binding:ExactRemoteJobBinding,current_profile:ServerProfile,*,input_binding_observation_id:str,requests:tuple[ExactArtifactRequest,...],capture_sequence:int)->FetchedOutputCapture:
        authority,runtime,receipt=self._closed(snapshot,binding,current_profile); _validate_requests(requests)
        if type(capture_sequence) is not int or capture_sequence<1 or not isinstance(input_binding_observation_id,str) or not input_binding_observation_id.strip(): raise TransportBoundaryError("capture authority is invalid")
        prepared=snapshot.prepared_input_binding.logical_name
        if not prepared.endswith(".gjf"): raise TransportBoundaryError("prepared input has no Gaussian basename")
        required_log=prepared[:-4]+".log"; required=tuple(x for x in requests if x.required)
        if len(required)!=1 or required[0].artifact_kind!="gaussian-log" or required[0].logical_name!=required_log or required[0].remote_relative_name!=required_log: raise TransportBoundaryError("fetch does not bind exact required log")
        workspace=self._store._workspace(snapshot); closed={**_workspace_binding(snapshot,runtime,workspace),"job_authority_id":receipt["job_authority_id"],"receipt_binding_id":receipt["receipt_binding_id"],"remote_effect_receipt_id":binding.remote_effect_receipt_id,"job_id":binding.job_id}
        artifacts=[]; status="captured"; total=0
        for request in requests:
            stat_op=_operation("STAT_EXACT_FILE"); stat_inv=_Invocation(operation=stat_op,argv=(request.remote_relative_name,),cwd=binding.remote_workspace,request=_request(stat_op.name,closed,{"remote_relative_name":request.remote_relative_name}),authority=authority)
            try: stat_result=_result_object(self._driver.invoke_text(snapshot,stat_inv))
            except Exception: status="capture-interrupted"; break
            if stat_result.get("presence")=="absent": status="capture-in-progress"; break
            if set(stat_result)!={"presence","remote_relative_name","size_bytes","file_physical_token_base64"} or stat_result["presence"]!="present" or stat_result["remote_relative_name"]!=request.remote_relative_name: raise TransportBoundaryError("stat result is malformed")
            announced_size=stat_result["size_bytes"]; announced_token=stat_result["file_physical_token_base64"]
            if type(announced_size) is not int or announced_size<0 or announced_size>MAX_FETCH_ARTIFACT_BYTES or total+announced_size>MAX_FETCH_CAPTURE_BYTES: raise TransportBoundaryError("announced capture exceeds cap")
            if type(announced_token) is not str: raise TransportBoundaryError("stat file identity is malformed")
            fetch_op=_operation("FETCH_EXACT_FILE"); payload={"remote_relative_name":request.remote_relative_name,"expected_size_bytes":stat_result["size_bytes"],"expected_file_physical_token_base64":stat_result["file_physical_token_base64"]}; fetch_inv=_Invocation(operation=fetch_op,argv=(request.remote_relative_name,),cwd=binding.remote_workspace,request=_request(fetch_op.name,closed,payload),authority=authority)
            try: result=self._driver.invoke_fetch(snapshot,fetch_inv)
            except Exception: result=_FetchResult(status="transport-error")
            if not _is_fetch_result_closed(result) or result.status!="found": status="capture-interrupted"; break
            content=result.content; digest=sha256(content).hexdigest()
            if result.before_identity!=announced_token or result.after_identity!=announced_token or result.before_size!=announced_size or result.after_size!=announced_size or result.before_size!=len(content) or result.before_sha256!=digest or result.after_sha256!=digest: raise TransportBoundaryError("fetched source changed")
            if len(content)>MAX_FETCH_ARTIFACT_BYTES or total+len(content)>MAX_FETCH_CAPTURE_BYTES: raise TransportBoundaryError("fetched capture exceeds cap")
            total+=len(content); artifacts.append(FetchedArtifact(request=request,content=content))
        if not artifacts: raise TransportBoundaryError("zero stable artifacts cannot create capture")
        missing=requests[len(artifacts):]
        return FetchedOutputCapture(binding=binding,input_binding_observation_id=input_binding_observation_id,capture_sequence=capture_sequence,capture_status=status,capture_completeness="complete" if not missing else "partial",requests=requests,artifacts=tuple(artifacts),missing_requests=missing,captured_at_utc=self._clock())

__all__=["RTWinExecutionAdapter","RTWinReadAdapter"]
