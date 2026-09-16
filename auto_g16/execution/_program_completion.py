"""Private C2/C3 completion grammar; decoding never grants effect authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import base64
import json
import math
import re
import shlex

from ._identity import ExecutionValueError, freeze_mapping, require_sha256, require_text, semantic_sha256
from ._paths import validate_portable_name, validate_posix_path
from .models import ResolvedServerProfile, ServerProfile, resolve_server_profile, _canonical_xtb_runtime_data_manifest


_MODE = "receipt-on-absence-v1"
_SCHEMA = "auto-g16-v31-program-completion/1"
_RECEIPT_CAP = 65536
_RECEIPT_FIELDS = frozenset({
    "schema", "pre_execution_binding_sha256", "attempt_id",
    "program_execution_snapshot_id", "effect_intent_id", "job_id",
    "workspace_binding_id", "remote_workspace", "workspace_physical_token",
    "program_execution_spec_id", "program_execution_spec_payload_sha256",
    "program_kind", "adapter_id", "adapter_contract_version", "operation",
    "completion_mode", "wrapper_source_sha256", "wrapper_source_size_bytes",
    "submit_marker_sha256", "inputs", "outputs", "termination", "finished_at",
})
_INPUT_FIELDS = frozenset({"logical_role", "portable_name", "format", "size_bytes", "sha256"})
_OUTPUT_FIELDS = _INPUT_FIELDS | {"presence"}
_RESERVED_NAMES = frozenset({
    "v31-completion-launch.lock", "v31-completion.pending", "v31-completion.json",
    ".auto-g16-v31-submit-intent", ".auto-g16-v31-submitted",
})
_DIGEST_FIELDS = frozenset({
    "pre_execution_binding_sha256", "program_execution_spec_payload_sha256",
    "wrapper_source_sha256", "submit_marker_sha256",
})
_ID_FIELDS = frozenset({
    "attempt_id", "program_execution_snapshot_id", "effect_intent_id", "job_id",
    "workspace_binding_id", "workspace_physical_token", "program_execution_spec_id",
})
_METADATA_DECLARATION = freeze_mapping({
    "logical_role": "completion-receipt", "portable_name": "v31-completion.json",
    "format": "json", "cardinality": "exactly-one", "max_size_bytes": _RECEIPT_CAP,
    "capture_policy": "exact-file", "completeness": "program-success",
}, "completion receipt declaration")


class _CompletionValueError(ExecutionValueError):
    """Invalid evidence. No program return code can be inferred from this error."""


def _closed(value: object, keys: frozenset[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _CompletionValueError(f"{label}: exact closed fields required")
    return value


def _integer(value: object, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _CompletionValueError(f"{label}: integer outside allowed range")
    return value


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _CompletionValueError("duplicate JSON field")
        result[key] = value
    return result


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise _CompletionValueError("unsupported JSON value")


def _receipt_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        _plain(value), ensure_ascii=False, allow_nan=False,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8") + b"\n"


def _file_members(value: object, *, outputs: bool) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise _CompletionValueError("file inventory must be nonempty and ordered")
    names: set[str] = set()
    roles: set[str] = set()
    result = []
    for member in value:
        item = _closed(member, _OUTPUT_FIELDS if outputs else _INPUT_FIELDS, "file")
        for key in ("logical_role", "portable_name", "format"):
            require_text(item[key], key)
        name = validate_portable_name(item["portable_name"], "portable_name")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is None or name in names or item["logical_role"] in roles or name in _RESERVED_NAMES:
            raise _CompletionValueError("duplicate or reserved file identity")
        names.add(name)
        roles.add(item["logical_role"])
        presence = item["presence"] if outputs else "present"
        if presence == "absent":
            if item["size_bytes"] is not None or item["sha256"] is not None:
                raise _CompletionValueError("absent output carries content identity")
        elif presence == "present":
            _integer(item["size_bytes"], 0 if outputs else 1, 64 * 1024 * 1024, "size_bytes")
            require_sha256(item["sha256"], "sha256")
        else:
            raise _CompletionValueError("unknown output presence")
        result.append(freeze_mapping(item, "receipt file"))
    return tuple(result)


def _validate_receipt_shape(value: object) -> Mapping[str, object]:
    """Validate serialization only; a well-formed forged file is still untrusted."""
    item = _closed(value, _RECEIPT_FIELDS, "completion receipt")
    if (
        item["schema"] != _SCHEMA or item["program_kind"] != "xtb"
        or item["adapter_id"] != "auto-g16-v31-xtb"
        or type(item["adapter_contract_version"]) is not int
        or item["adapter_contract_version"] != 3
        or item["completion_mode"] != _MODE
        or item["operation"] not in {"single-point", "optimize"}
    ):
        raise _CompletionValueError("unknown completion version or operation")
    for key in _DIGEST_FIELDS:
        require_sha256(item[key], key)
    for key in _ID_FIELDS:
        require_text(item[key], key)
    validate_portable_name(item["attempt_id"], "attempt_id")
    validate_portable_name(item["job_id"], "job_id")
    validate_posix_path(item["remote_workspace"], "remote_workspace")
    _integer(item["wrapper_source_size_bytes"], 1, 64 * 1024 * 1024, "wrapper size")
    inputs = _file_members(item["inputs"], outputs=False)
    outputs = _file_members(item["outputs"], outputs=True)
    if {x["portable_name"] for x in inputs} & {x["portable_name"] for x in outputs}:
        raise _CompletionValueError("input/output name collision")
    termination = _closed(item["termination"], frozenset({"kind", "returncode", "signal"}), "termination")
    if termination["kind"] == "exited" and termination["signal"] is None:
        _integer(termination["returncode"], 0, 255, "returncode")
    elif termination["kind"] == "signaled" and termination["returncode"] is None:
        _integer(termination["signal"], 1, 64, "signal")
    else:
        raise _CompletionValueError("contradictory termination fields")
    stamp = item["finished_at"]
    if not isinstance(stamp, str) or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", stamp) is None:
        raise _CompletionValueError("finished_at must be canonical UTC")
    try:
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise _CompletionValueError("invalid finished_at calendar value") from exc
    return freeze_mapping({**item, "inputs": inputs, "outputs": outputs}, "completion receipt")


def _decode_receipt(content: bytes) -> Mapping[str, object]:
    if type(content) is not bytes or not content or len(content) > _RECEIPT_CAP:
        raise _CompletionValueError("receipt bytes unavailable or oversized")
    try:
        decoded = json.loads(content.decode("utf-8"), object_pairs_hook=_json_pairs)
        value = _validate_receipt_shape(decoded)
        if _receipt_json(value) != content:
            raise _CompletionValueError("noncanonical receipt bytes")
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise _CompletionValueError("receipt-invalid") from exc


def _xyz_elements(content: bytes) -> tuple[str, ...]:
    """Structural closure only. This is not convergence or scientific acceptance."""
    if type(content) is not bytes or not content or len(content) > 64 * 1024 * 1024:
        raise _CompletionValueError("XYZ bytes unavailable or oversized")
    try:
        text = content.decode("utf-8")
        if "\x00" in text:
            raise ValueError("NUL")
        lines = text.splitlines()
        if not lines or re.fullmatch(r"[1-9][0-9]*", lines[0]) is None:
            raise ValueError("count")
        count = int(lines[0])
        if len(lines) < count + 2 or any(line.strip() for line in lines[count + 2:]):
            raise ValueError("cardinality")
        elements = []
        symbols = set((
            "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
            "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La "
            "Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi "
            "Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
        ).split())
        for line in lines[2:count + 2]:
            tokens = line.split()
            if len(tokens) != 4 or tokens[0] not in symbols:
                raise ValueError("atom")
            if not all(math.isfinite(float(token)) for token in tokens[1:]):
                raise ValueError("coordinate")
            elements.append(tokens[0])
        return tuple(elements)
    except (ValueError, UnicodeError, OverflowError) as exc:
        raise _CompletionValueError("output-invalid") from exc


def _output_closure(operation: str, input_content: bytes, outputs: Mapping[str, bytes | None]) -> str | None:
    """Return a closed failure diagnostic; the caller must first establish provenance."""
    if operation not in {"single-point", "optimize"} or set(outputs) != {"xtb.out", "xtbopt.xyz"}:
        raise _CompletionValueError("output inventory differs from the closed xTB operation")
    if outputs["xtb.out"] is None or (operation == "optimize" and outputs["xtbopt.xyz"] is None):
        return "output-incomplete"
    try:
        log = outputs["xtb.out"]
        if type(log) is not bytes or not log or len(log) > 64 * 1024 * 1024 or "\x00" in log.decode("utf-8"):
            return "output-invalid"
        original = _xyz_elements(input_content)
        geometry = outputs["xtbopt.xyz"]
        if geometry is not None and _xyz_elements(geometry) != original:
            return "output-invalid"
    except (UnicodeError, _CompletionValueError):
        return "output-invalid"
    return None


# C3 pure projection, extracted from the existing manifest-v3 Transport grammar.
# No Transport import or deployment/driver construction belongs in this module.

_MATERIAL_SCHEMA = "v31-completion-rendering-material/1"
_DEPLOYMENT_NAME = "transport-deployment-manifest-v3.json"
_DATA_NAME = "xtb-runtime-data-manifest-v1.json"
_MATERIAL_FIELDS = frozenset({"schema", "resolved_server_profile_id", "deployment_manifest_base64", "xtb_runtime_data_manifest_base64"})
_DATA_LINE = "# completion-material-base64: "
_ROOT_FIELDS = frozenset({"attestation_mode", "deployment_identity", "expected_sha256", "expected_size_bytes", "path", "platform", "shell_grammar"})
_ROOT_RULES = {
    "mac_ssh": ("macos", "controller-file-v1"),
    "server_remote_shell": ("posix", "deployment-root-v1"),
    "server_python": ("posix", "server-self-check-v1"),
    "server_qsub": ("posix", "server-python-file-v1"),
    "server_qstat": ("posix", "server-python-file-v1"),
}


def _unbase64(value: object, cap: int) -> bytes:
    if type(value) is not str or len(value) > 4 * ((cap + 2) // 3):
        raise _CompletionValueError("base64 cap/type")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
        if len(raw) > cap or base64.b64encode(raw).decode("ascii") != value:
            raise _CompletionValueError("noncanonical base64")
        return raw
    except (ValueError, UnicodeError) as exc:
        raise _CompletionValueError("invalid base64") from exc


def _canonical_json_object(raw: bytes, cap: int) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > cap:
        raise _CompletionValueError("JSON cap/type")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs)
        if not isinstance(value, dict) or _receipt_json(value) != raw:
            raise _CompletionValueError("noncanonical JSON object")
        return value
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise _CompletionValueError("invalid canonical JSON") from exc


def _deployment_projection(raw: bytes) -> Mapping[str, object]:
    value = _closed(_canonical_json_object(raw, 1024 * 1024), frozenset({"schema", "deployment_id", "bootstrap_protocol", "trust_roots"}), "deployment manifest")
    if value["schema"] != "auto-g16-v3-transport-deployment-manifest/3" or value["bootstrap_protocol"] != "auto-g16-v31-rtwin-bootstrap/1":
        raise _CompletionValueError("unsupported deployment manifest")
    require_text(value["deployment_id"], "deployment_id")
    if any(character in value["deployment_id"] for character in "\r\n"):
        raise _CompletionValueError("deployment identity contains a line break")
    roots = _closed(value["trust_roots"], frozenset(_ROOT_RULES), "trust roots")
    for name, (platform, mode) in _ROOT_RULES.items():
        root = _closed(roots[name], _ROOT_FIELDS, name)
        if root["platform"] != platform or root["attestation_mode"] != mode:
            raise _CompletionValueError("trust-root platform/mode")
        validate_posix_path(root["path"], name + ".path")
        require_text(root["deployment_identity"], name + ".deployment_identity")
        if any(character in root["deployment_identity"] for character in "\r\n"):
            raise _CompletionValueError("root deployment identity contains a line break")
        if name == "server_remote_shell":
            if root["expected_sha256"] is not None or root["expected_size_bytes"] is not None or root["shell_grammar"] != "posix-sh-v1":
                raise _CompletionValueError("shell trust grammar")
        else:
            require_sha256(root["expected_sha256"], name + ".sha256")
            _integer(root["expected_size_bytes"], 1, 2**63 - 1, name + ".size")
            if root["shell_grammar"] is not None:
                raise _CompletionValueError("file trust grammar")
    return freeze_mapping(value, "manifest-v3 projection")


def _validate_material(material: object, profile: ResolvedServerProfile) -> Mapping[str, object]:
    profile.assert_identity_closed()
    value = _closed(material, _MATERIAL_FIELDS, "completion rendering material")
    if value["schema"] != _MATERIAL_SCHEMA or value["resolved_server_profile_id"] != profile.resolved_server_profile_id:
        raise _CompletionValueError("material profile/schema mismatch")
    if len(_receipt_json(value)) > 3 * 1024 * 1024:
        raise _CompletionValueError("material cap")
    for key, name in (("deployment_manifest_base64", _DEPLOYMENT_NAME), ("xtb_runtime_data_manifest_base64", _DATA_NAME)):
        content = _unbase64(value[key], 1024 * 1024)
        expected = profile.runtime_identities.get(name)
        if expected != {"sha256": sha256(content).hexdigest(), "size_bytes": len(content)}:
            raise _CompletionValueError("material differs from profile runtime identity")
        if name == _DEPLOYMENT_NAME:
            _deployment_projection(content)
        elif _canonical_xtb_runtime_data_manifest(content) != content:
            raise _CompletionValueError("runtime data manifest is not canonical")
    return freeze_mapping(value, "rendering material")


def _prepare_completion_rendering_material(current_profile: ServerProfile, resolved_profile: ResolvedServerProfile) -> Mapping[str, object]:
    if type(current_profile) is not ServerProfile or type(resolved_profile) is not ResolvedServerProfile:
        raise _CompletionValueError("exact profile types required")
    current = resolve_server_profile(current_profile)
    if current != resolved_profile or current.semantic_payload() != resolved_profile.semantic_payload():
        raise _CompletionValueError("current profile drift")
    try:
        deployment = current_profile.runtime_contents[_DEPLOYMENT_NAME]
        data = _canonical_xtb_runtime_data_manifest(current_profile.runtime_contents[_DATA_NAME])
    except KeyError as exc:
        raise _CompletionValueError("missing rendering material") from exc
    return _validate_material({
        "schema": _MATERIAL_SCHEMA, "resolved_server_profile_id": resolved_profile.resolved_server_profile_id,
        "deployment_manifest_base64": base64.b64encode(deployment).decode("ascii"),
        "xtb_runtime_data_manifest_base64": base64.b64encode(data).decode("ascii"),
    }, resolved_profile)


def _material_from_artifact(artifacts: tuple[Mapping[str, object], ...], profile: ResolvedServerProfile) -> Mapping[str, object]:
    if len(artifacts) != 1 or type(artifacts[0].get("content_utf8")) is not str:
        raise _CompletionValueError("one exact scheduler artifact required")
    lines = artifacts[0]["content_utf8"].splitlines()
    if len(lines) < 3 or lines[:2] != ["#!/bin/bash", "# auto-g16-v31-scheduler/2"] or not lines[2].startswith(_DATA_LINE) or sum(line.startswith(_DATA_LINE) for line in lines) != 1:
        raise _CompletionValueError("missing/relocated/duplicate rendering material")
    raw = _unbase64(lines[2][len(_DATA_LINE):], 3 * 1024 * 1024)
    return _validate_material(_canonical_json_object(raw, 3 * 1024 * 1024), profile)


def _prebinding(fields: Mapping[str, object], material: Mapping[str, object]) -> Mapping[str, object]:
    from ._program_completion_wrapper import _WRAPPER_SOURCE
    expected = frozenset({"attempt_id", "calculation_plan_id", "calculation_plan_revision", "program_execution_spec_id", "program_execution_spec_payload_sha256", "project_physical_binding_id", "resolved_resource_request_id", "resolved_server_profile_id", "workspace_binding_id", "cwd_binding"})
    _closed(fields, expected, "snapshot prebinding fields")
    source = _WRAPPER_SOURCE.encode("utf-8")
    return freeze_mapping({**fields, "binding_schema": "v31-completion-prebinding/2", "wrapper_source_sha256": sha256(source).hexdigest(), "wrapper_source_size_bytes": len(source), "rendering_material_sha256": semantic_sha256(material)}, "completion prebinding")


def _render_completion_scheduler(spec, resources, profile, fields, material):
    from ._program_completion_wrapper import _WRAPPER_SOURCE
    material = _validate_material(material, profile)
    binding = _prebinding(fields, material)
    deployment = _deployment_projection(_unbase64(material["deployment_manifest_base64"], 1024 * 1024))
    config = {
        "prebinding": binding, "prebinding_sha256": semantic_sha256(binding),
        "spec": spec.semantic_payload(), "material": material,
        "xtb_data_path": profile.platform_paths["xtb_data_path"],
        "cores": resources.cores, "walltime_seconds": resources.walltime_seconds,
    }
    lines = ["#!/bin/bash", "# auto-g16-v31-scheduler/2", _DATA_LINE + base64.b64encode(_receipt_json(material)).decode("ascii"),
        f"#PBS -l nodes=1:ppn={resources.cores}", f"#PBS -l mem={resources.memory_mb}mb", f"#PBS -l walltime={resources.walltime_seconds}"]
    if resources.queue is not None:
        lines.append(f"#PBS -q {resources.queue}")
    arguments = (deployment["trust_roots"]["server_python"]["path"], "-I", "-S", "-B", "-c", _WRAPPER_SOURCE, base64.b64encode(_receipt_json(config)).decode("ascii"))
    lines.append("exec " + " ".join(shlex.quote(str(x)) for x in arguments))
    content = ("\n".join(lines) + "\n").encode("utf-8")
    return (freeze_mapping({"logical_role": "scheduler-script", "portable_name": "xtb.pbs", "format": "pbs-shell-utf8", "sha256": sha256(content).hexdigest(), "size_bytes": len(content), "content_utf8": content.decode("utf-8")}, "completion scheduler"),)


def _receipt_binding(snapshot, job_id: str, workspace_token: str) -> Mapping[str, object]:
    """Expected values come exclusively from reclosed approved predecessors."""
    snapshot.assert_identity_closed()
    binding = _prebinding({key: value for key, value in snapshot._identity_payload.items() if key != "scheduler_artifacts"}, snapshot._completion_material())
    spec = snapshot.program_execution_spec
    marker = {"program_execution_snapshot_id": snapshot.program_execution_snapshot_id, "effect_intent_id": snapshot.effect_intent_id}
    return freeze_mapping({
        "schema": _SCHEMA, "pre_execution_binding_sha256": semantic_sha256(binding),
        "attempt_id": snapshot.attempt_id, **marker, "job_id": job_id,
        "workspace_binding_id": snapshot.workspace_binding.workspace_binding_id,
        "remote_workspace": snapshot.workspace_binding.remote_attempt_dir,
        "workspace_physical_token": workspace_token,
        "program_execution_spec_id": spec.program_execution_spec_id,
        "program_execution_spec_payload_sha256": snapshot.program_execution_spec_payload_sha256,
        "program_kind": "xtb", "adapter_id": spec.adapter_id, "adapter_contract_version": 3,
        "operation": spec.program_data["task"], "completion_mode": _MODE,
        "wrapper_source_sha256": binding["wrapper_source_sha256"],
        "wrapper_source_size_bytes": binding["wrapper_source_size_bytes"],
        "submit_marker_sha256": sha256(_receipt_json(marker)).hexdigest(), "inputs": spec.exact_inputs,
    }, "expected completion binding")


def _bound_receipt(raw: bytes, snapshot, job_id: str, workspace_token: str) -> Mapping[str, object]:
    receipt = _decode_receipt(raw)
    expected = _receipt_binding(snapshot, job_id, workspace_token)
    if any(receipt[key] != item for key, item in expected.items()):
        raise _CompletionValueError("receipt binding differs from approved authority")
    declarations = (*snapshot.program_execution_spec.required_outputs, *snapshot.program_execution_spec.optional_outputs)
    if len(declarations) != len(receipt["outputs"]):
        raise _CompletionValueError("receipt output inventory differs")
    for declaration, item in zip(declarations, receipt["outputs"]):
        if any(item[key] != declaration[key] for key in ("logical_role", "portable_name", "format")) or (item["presence"] == "present" and item["size_bytes"] > min(declaration["max_size_bytes"], 64 * 1024 * 1024)):
            raise _CompletionValueError("receipt output inventory differs")
    return receipt


__all__: tuple[str, ...] = ()
