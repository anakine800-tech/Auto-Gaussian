"""Historical content projection; no execution or scientific acceptance authority."""
from dataclasses import dataclass, field
from hashlib import sha256
import json
from types import SimpleNamespace

from . import program as owner
from . import program_runtime as runtime
from . import _program_completion as completion
from ._identity import canonical_bytes, freeze_mapping, semantic_id, semantic_sha256
from .models import ExecutionValueError


@dataclass(frozen=True, kw_only=True)
class ProgramReadSnapshot:
    """Startup-only immutable bytes, pinned by an explicitly supplied digest."""
    content: bytes = field(repr=False)
    sha256: str

    def __post_init__(self):
        if type(self.content) is not bytes or len(self.content) > 16 * 1024 * 1024 or sha256(self.content).hexdigest() != self.sha256:
            raise ExecutionValueError("invalid historical snapshot registration")
        # Validate once at registration; retain bytes rather than mutable caller data.
        _snapshot(self)

    @property
    def attempt_id(self):
        return json.loads(self.content)["attempt_id"]


def _check(condition, reason="historical persisted evidence differs"):
    if not condition:
        raise ExecutionValueError(reason)


def _snapshot(registration):
    def pairs(items):
        result = {}
        for key, value in items:
            _check(key not in result)
            result[key] = value
        return result
    raw = json.loads(registration.content, object_pairs_hook=pairs)
    value, spec, binding, resources, profile, workspace = owner._decode_program_review_components(raw)
    owner._assert_executable_matches_resolved_profile(spec, profile)
    owner._validate_gaussian_resource_binding(spec, resources)
    payload = freeze_mapping({key: value[key] for key in owner._SNAPSHOT_PAYLOAD_FIELDS}, "historical snapshot")
    for key, expected in {
        "program_execution_spec_id": spec.program_execution_spec_id,
        "program_execution_spec_payload_sha256": semantic_sha256(spec.semantic_payload()),
        "project_physical_binding_id": binding.project_physical_binding_id,
        "resolved_resource_request_id": resources.resolved_resource_request_id,
        "resolved_server_profile_id": profile.resolved_server_profile_id,
        "workspace_binding_id": workspace.workspace_binding_id,
        "cwd_binding": freeze_mapping({"location_kind": "server", "path": workspace.remote_attempt_dir}, "cwd"),
    }.items():
        _check(payload[key] == expected)
    _check(binding.project_id == workspace.project_id and workspace.attempt_id == value["attempt_id"])
    _check(binding.resolved_server_profile_id == profile.resolved_server_profile_id)
    _check(binding.resolved_target_identity == profile.target_identity and binding.remote_root == profile.remote_root)
    _check(workspace.remote_attempt_dir == f"{binding.remote_project_dir}/{value['attempt_id']}")
    artifacts = payload["scheduler_artifacts"]
    single = (("scheduler-script", f"{spec.program_kind}.pbs", "pbs-shell-utf8"),)
    allowed = {single}
    if spec.program_kind == "crest" and spec.adapter_contract_version == 3:
        allowed.add((*single, ("startup-payload", "crest-startup.json", "json")))
    if spec.program_kind == "gaussian" and spec.adapter_contract_version in (4, 5, 6):
        first = "gaussian-entry-template.pbs" if spec.adapter_contract_version in (5, 6) else "gaussian.pbs"
        allowed = {(("scheduler-script", first, "pbs-shell-utf8"), ("startup-payload", "gaussian-startup.json", "canonical-json-utf8"))}
    _check(type(artifacts) is tuple)
    _check(tuple((a["logical_role"], a["portable_name"], a["format"]) for a in artifacts) in allowed)
    for artifact in artifacts:
        owner._exact_keys(artifact, {"logical_role", "portable_name", "format", "sha256", "size_bytes", "content_utf8"}, "historical scheduler")
        _check(type(artifact["size_bytes"]) is int and type(artifact["content_utf8"]) is str)
        content = artifact["content_utf8"].encode("utf-8")
        _check(len(content) == artifact["size_bytes"] and sha256(content).hexdigest() == artifact["sha256"])
    intent = semantic_id("program-effect-intent", payload)
    _check(value["effect_intent_id"] == intent)
    _check(value["program_execution_snapshot_id"] == semantic_id("program-execution-snapshot", {"effect_intent_id": intent, **payload}))
    # Private data carrier, never an executable ProgramExecutionSnapshot.
    return SimpleNamespace(**{key: value[key] for key in ("attempt_id", "effect_intent_id", "program_execution_snapshot_id", "calculation_plan_id", "calculation_plan_revision")},
        program_execution_spec=spec, workspace_binding=workspace,
        project_physical_binding=binding, resolved_resource_request=resources, resolved_server_profile=profile,
        program_execution_spec_payload_sha256=payload["program_execution_spec_payload_sha256"])


class _ReadPrefixDigests:
    """Request-local exact Execution canonical prefix hashes; no evidence cache."""
    def __init__(self, observations):
        self._observations = observations
        self._next = 0
        self._hash = sha256(b'["sequence",[')

    def before(self, index):
        if index < self._next or index > len(self._observations):
            raise ExecutionValueError("prefix indices must be monotonic")
        while self._next < index:
            item = self._observations[self._next]
            if self._next:
                self._hash.update(b',')
            self._hash.update(canonical_bytes({"observation_id": item.observation_id,
                "attempt_id": item.attempt_id, "observation_type": item.observation_type,
                "data": item.data}))
            self._next += 1
        prefix = self._hash.copy()
        prefix.update(b']]')
        return prefix.hexdigest()


def _verify_read_assessments(observations, snapshot, job):
    """Same assessment contract as runtime; only prefix computation differs.

    Keep the differential tests in sync if the runtime contract changes. This
    historical read optimization intentionally does not alter execution paths.
    """
    prefixes = _ReadPrefixDigests(observations)
    for index, item in enumerate(observations):
        if item.observation_type != runtime._COMPLETION_ASSESSMENT:
            continue
        data = completion._closed(item.data, runtime._COMPLETION_ASSESSMENT_KEYS, "completion assessment")
        prefix = observations[:index]
        ids = tuple(member.observation_id for member in prefix)
        selected = data["evidence_observation_ids"]
        expected_ids = tuple(member.observation_id for member in prefix if member.observation_type == runtime._transport._RECEIPT_TYPE)
        if selected != expected_ids:
            raise runtime.TransportBoundaryError("completion assessment omits exact evidence sources")
        completion.require_sha256(data["observation_prefix_sha256"], "completion prefix digest")
        for key in ("epoch_id", "evidence_result_id", "capture_authority_id"):
            if data[key] is not None:
                completion.require_text(data[key], key)
        if data["receipt_sha256"] is not None:
            completion.require_sha256(data["receipt_sha256"], "completion receipt digest")
        if data["schema"] != runtime._COMPLETION_ASSESSMENT or data["completion_mode"] != completion._MODE or any(data[key] != value for key, value in runtime._completion_binding(snapshot, job).items()) or item.observation_id != semantic_id("program-completion-assessment", data) or data["observation_prefix_sha256"] != prefixes.before(index) or not isinstance(selected, tuple) or len(set(selected)) != len(selected) or any(key not in ids for key in selected) or tuple(key for key in ids if key in selected) != selected or data["diagnostic"] not in runtime._COMPLETION_DIAGNOSTICS or data["verdict"] != runtime._completion_verdict(data["diagnostic"]):
            raise runtime.TransportBoundaryError("completion assessment or prefix is corrupt")
        if data["verdict"] != "UNKNOWN" and any(data[key] is None for key in ("epoch_id", "evidence_result_id", "capture_authority_id", "receipt_sha256")):
            raise runtime.TransportBoundaryError("terminal completion assessment lacks captured provenance")



class ProgramReadQuery:
    """Use only a caller-owned Core read view. No filesystem access or constructor."""
    def __init__(self, reader):
        self._reader = reader

    def get_summary(self, registration: ProgramReadSnapshot):
        _check(type(registration) is ProgramReadSnapshot)
        snapshot = _snapshot(registration)
        store = self._reader
        attempt = store.load_attempt(snapshot.attempt_id)
        task = store.load_task(attempt.task_id)
        run = store.load_workflow_run(task.workflow_run_id)
        plan = store.load_calculation_plan(snapshot.calculation_plan_id)
        resource = store.load_resource_spec(snapshot.resolved_resource_request.resource_spec_id)
        _check(attempt.attempt_id == snapshot.attempt_id and task.task_id == attempt.task_id)
        _check(run.workflow_run_id == task.workflow_run_id and plan.calculation_plan_id == snapshot.calculation_plan_id)
        _check(resource.resource_spec_id == snapshot.resolved_resource_request.resource_spec_id)
        _check(plan.task_id == task.task_id and plan.revision == snapshot.calculation_plan_revision)
        _check(resource.task_id == task.task_id and run.project_id == snapshot.project_physical_binding.project_id)
        _check(store.load_submission_intent(snapshot.attempt_id) == snapshot.effect_intent_id)
        receipts = runtime._load_receipts(store, snapshot)
        observations = store.observations_for_attempt(snapshot.attempt_id)
        all_results = store.results_for_attempt(snapshot.attempt_id)
        _check(all(r.attempt_id == snapshot.attempt_id for r in all_results))
        _check(all(o.attempt_id == snapshot.attempt_id for o in observations))
        results = [r for r in all_results if r.result_type == runtime._COMPLETION_EVIDENCE]
        _check(len(results) <= 1)
        spec = snapshot.program_execution_spec
        summary = {"schema": "program-read-summary/1", "scope": "historical-core-content-associations",
                   "snapshot_id": snapshot.program_execution_snapshot_id, "snapshot_sha256": registration.sha256,
                   "effect_intent_id": snapshot.effect_intent_id, "program": spec.program_kind,
                   "adapter_id": spec.adapter_id, "adapter_contract_version": spec.adapter_contract_version,
                   "bound_plan": {"id": plan.calculation_plan_id, "revision": plan.revision},
                   "inputs": [dict(item) for item in spec.exact_inputs], "artifacts": [],
                   "capture": None, "assessments": [], "scientific_facts": "unsupported-native-result-contract" if len(all_results) != len(results) else "not-recorded"}
        identity_binding = {
            "attempt_id": snapshot.attempt_id,
            "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
            "effect_intent_id": snapshot.effect_intent_id,
            "program_execution_spec_id": spec.program_execution_spec_id,
            "project_physical_binding_id": snapshot.project_physical_binding.project_physical_binding_id,
            "workspace_binding_id": snapshot.workspace_binding.workspace_binding_id,
            "resolved_server_profile_id": snapshot.resolved_server_profile.resolved_server_profile_id,
            "remote_workspace": snapshot.workspace_binding.remote_attempt_dir,
        }
        declared_bases = set()
        for receipt in receipts:
            request = receipt.data["request"]
            bound = request["binding"]
            runtime._transport._validate_program_effect_request(request, bound)
            _check(request["operation"] == receipt.data["operation"])
            _check(all(bound[k] == v for k, v in identity_binding.items()))
            declared_bases.add(tuple(bound[k] for k in ("program_transport_store_id", "store_instance_id", "runtime_attestation_id")))
        _check(len(declared_bases) <= 1)
        if not results:
            # An existing assessment without its referenced bundle is not a clean absence.
            _check(not any(o.observation_type == runtime._COMPLETION_ASSESSMENT for o in observations))
            return summary
        record = results[0]
        data = completion._closed(record.data, frozenset({"schema", *runtime._COMPLETION_BINDING_KEYS, "epoch_id", "inputs", "captured_files"}), "historical completion")
        _check(record.attempt_id == snapshot.attempt_id and data["schema"] == runtime._COMPLETION_EVIDENCE)
        _check(record.result_id == semantic_id("program-completion-evidence", data))
        job = {"job_authority_id": data["job_authority_id"]}
        _check(all(data[k] == v for k, v in runtime._completion_binding(snapshot, job).items()))
        by_id = {r.observation_id: r for r in receipts}
        positions = {r.observation_id: i for i, r in enumerate(observations)}
        openings = [r for r in receipts if r.data["operation"] == "QUERY_SCHEDULER" and r.data["outcome"] == "SUCCEEDED" and r.data["response"]["state"] == "absent" and runtime._completion_epoch(snapshot, job, r) == data["epoch_id"]]
        _check(len(openings) == 1)
        opening = openings[0]
        _check(type(data["inputs"]) is tuple and len(data["inputs"]) == len(spec.exact_inputs))
        inputs = {}
        for member, declaration in zip(data["inputs"], spec.exact_inputs):
            completion._closed(member, completion._INPUT_FIELDS | {"content_base64", "stage_observation_id"}, "historical input")
            _check(all(member[k] == v for k, v in declaration.items()))
            inputs[declaration["portable_name"]] = completion._unbase64(member["content_base64"], 64 * 1024 * 1024)
            _check(positions[member["stage_observation_id"]] < positions[opening.observation_id])
        _check(freeze_mapping({"inputs": runtime._completion_inputs(snapshot, receipts, inputs)}, "inputs")["inputs"] == data["inputs"])
        declarations = (completion._METADATA_DECLARATION, *spec.required_outputs, *spec.optional_outputs)
        files = data["captured_files"]
        _check(type(files) is tuple and len(files) == len(declarations))
        seen, restats, metadata, metadata_digest, artifacts = [], [], None, None, []
        for index, (member, declaration) in enumerate(zip(files, declarations)):
            completion._closed(member, completion._OUTPUT_FIELDS | {"content_base64", "stat_observation_id", "fetch_observation_id", "restat_observation_id"}, "historical file")
            _check(all(member[k] == declaration[k] for k in ("logical_role", "portable_name", "format")))
            first, last = (by_id[member[k]] for k in ("stat_observation_id", "restat_observation_id"))
            _check(all(r.data["operation"] == "STAT_EXACT_FILE" and r.data["outcome"] == "SUCCEEDED" for r in (first, last)))
            _check(first.data["request"]["payload"] == last.data["request"]["payload"] and first.data["response"] == last.data["response"])
            _check(first.data["response"]["portable_name"] == member["portable_name"] and first.data["response"]["presence"] == member["presence"])
            seen.append(first.observation_id); restats.append(last.observation_id)
            content = None
            if member["presence"] == "absent":
                _check(index > 0 and all(member[k] is None for k in ("content_base64", "fetch_observation_id", "size_bytes", "sha256")))
            else:
                _check(member["presence"] == "present")
                content = completion._unbase64(member["content_base64"], min(declaration["max_size_bytes"], 64 * 1024 * 1024))
                _check(len(content) == member["size_bytes"] and sha256(content).hexdigest() == member["sha256"])
                fetch = by_id[member["fetch_observation_id"]]
                _check(fetch.data["operation"] == "FETCH_EXACT_FILE" and fetch.data["outcome"] == "SUCCEEDED")
                _check(fetch.data["request"]["payload"]["stat_receipt_id"] == first.observation_id)
                _check(all(fetch.data["response"][k] == member[k] for k in ("portable_name", "size_bytes", "sha256")))
                _check(all(fetch.data["response"][k] == first.data["response"][k] for k in ("file_physical_token", "size_bytes")))
                seen.append(fetch.observation_id)
                if index == 0:
                    metadata = completion._decode_receipt(content)
                    metadata_digest = sha256(content).hexdigest()
            if index:
                summary["artifacts"].append({k: member[k] for k in completion._OUTPUT_FIELDS})
                artifacts.append(runtime._transport._ProgramOutputArtifact(str(member["logical_role"]), str(member["portable_name"]), str(member["format"]), str(member["presence"]), member["sha256"], member["size_bytes"], snapshot.program_execution_snapshot_id, snapshot.effect_intent_id, str(job["job_authority_id"]), member["fetch_observation_id"], content))
        ordered = [opening.observation_id, *seen, *restats]
        _check(len(set(ordered)) == len(ordered) and [positions[k] for k in ordered] == sorted(positions[k] for k in ordered))
        closing = next(r for r in receipts if r.data["operation"] == "QUERY_SCHEDULER" and positions[r.observation_id] > positions[restats[-1]])
        _check(closing.data["outcome"] == "SUCCEEDED" and closing.data["response"]["state"] == "absent")
        _check([r.observation_id for r in receipts if positions[opening.observation_id] <= positions[r.observation_id] <= positions[closing.observation_id]] == [*ordered, closing.observation_id])
        for receipt in receipts:
            binding = receipt.data["request"]["binding"]
            _check(binding["program_execution_snapshot_id"] == snapshot.program_execution_snapshot_id and binding["effect_intent_id"] == snapshot.effect_intent_id)
            if receipt in [by_id[k] for k in (*seen, *restats)] + [opening, closing]:
                _check(binding["job_authority_id"] == job["job_authority_id"])
        for later in receipts:
            if positions[later.observation_id] <= positions[closing.observation_id] or later.data["operation"] not in {"STAT_EXACT_FILE", "FETCH_EXACT_FILE"}:
                continue
            member = next((m for m in files if m["portable_name"] == later.data["request"]["payload"].get("portable_name")), None)
            _check(later.data["outcome"] == "SUCCEEDED" and member is not None, "late-capture-evidence-drift")
            predecessor_id = member["restat_observation_id" if later.data["operation"] == "STAT_EXACT_FILE" else "fetch_observation_id"]
            _check(predecessor_id in by_id and later.data["response"] == by_id[predecessor_id].data["response"], "late-capture-evidence-drift")
        _check(metadata is not None)
        establishing = [r for r in receipts if runtime._receipt_job_id(r.data) is not None]
        allocations = [r for r in receipts if r.data["operation"] == "ALLOCATE_WORKSPACE" and r.data["outcome"] == "SUCCEEDED"]
        _check(len(establishing) == 1 and len(allocations) == 1)
        expected_metadata = {
            "attempt_id": snapshot.attempt_id,
            "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
            "effect_intent_id": snapshot.effect_intent_id,
            "program_execution_spec_id": spec.program_execution_spec_id,
            "program_execution_spec_payload_sha256": snapshot.program_execution_spec_payload_sha256,
            "workspace_binding_id": snapshot.workspace_binding.workspace_binding_id,
            "remote_workspace": snapshot.workspace_binding.remote_attempt_dir,
            "workspace_physical_token": allocations[0].data["response"]["workspace_physical_token"],
            "job_id": runtime._receipt_job_id(establishing[0].data),
            "program_kind": spec.program_kind, "adapter_id": spec.adapter_id,
            "adapter_contract_version": 3, "completion_mode": completion._MODE,
            "operation": "imtd-gc" if spec.program_kind == "crest" else spec.program_data["stage"] if spec.program_kind == "gaussian" else spec.program_data["task"],
            "inputs": spec.exact_inputs,
            "outputs": tuple(freeze_mapping(a, "artifact") for a in summary["artifacts"]),
        }
        _check(all(metadata[k] == v for k, v in expected_metadata.items()), "completion-metadata-binding-mismatch")
        job_id = expected_metadata["job_id"]
        _check(all(r.data["request"]["payload"]["job_id"] == job_id for r in receipts if r.data["operation"] == "QUERY_SCHEDULER"))
        capture_payload = {"program_execution_snapshot_id": snapshot.program_execution_snapshot_id, "effect_intent_id": snapshot.effect_intent_id, "job_authority_id": job["job_authority_id"], "artifacts": tuple(a.identity_payload() for a in artifacts)}
        capture_id = runtime._transport._identity("output-capture", capture_payload)
        _verify_read_assessments(observations, snapshot, job)
        for assessment in observations:
            if assessment.observation_type != runtime._COMPLETION_ASSESSMENT:
                continue
            item = assessment.data
            if item["verdict"] != "UNKNOWN":
                _check(item["evidence_result_id"] == record.result_id and item["epoch_id"] == data["epoch_id"])
                _check(item["receipt_sha256"] == metadata_digest and item["capture_authority_id"] == capture_id, "terminal-assessment-capture-mismatch")
            summary["assessments"].append({"id": assessment.observation_id, "recorded_verdict": item["verdict"], "recorded_diagnostic": item["diagnostic"]})
        summary["capture"] = {"result_id": record.result_id, "epoch_id": data["epoch_id"],
                              "job_id": job_id, "integrity": "persisted-content-associations"}
        return summary
