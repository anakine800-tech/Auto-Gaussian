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
    header, binding_schema, source, cap = _completion_tuple(material)
    value = material
    if value["resolved_server_profile_id"] != profile.resolved_server_profile_id:
        raise _CompletionValueError("material profile/schema mismatch")
    if len(_receipt_json(value)) > cap:
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
    if value["schema"] == _PILOT_MATERIAL_SCHEMA:
        raw = _unbase64(value["publisher_qualification_base64"], _Q_CAP)
        if profile.runtime_identities.get(_Q_NAME) != {"sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}:
            raise _CompletionValueError("qualification differs from profile runtime bytes")
        q = _decode_publisher_qualification(raw)
        _validate_publisher_profile(q, profile, _deployment_projection(_unbase64(value["deployment_manifest_base64"], _Q_CAP)))
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
    if len(lines) < 3 or (lines[0] != "#!/bin/bash" or lines[1] not in {"# auto-g16-v31-scheduler/2", "# auto-g16-v31-scheduler/3"}) or not lines[2].startswith(_DATA_LINE) or sum(line.startswith(_DATA_LINE) for line in lines) != 1:
        raise _CompletionValueError("missing/relocated/duplicate rendering material")
    cap = (3 if lines[1].endswith("/2") else 5) * 1024 * 1024
    raw = _unbase64(lines[2][len(_DATA_LINE):], cap)
    material = _validate_material(_canonical_json_object(raw, cap), profile)
    if _completion_tuple(material)[0] != lines[1]:
        raise _CompletionValueError("mixed scheduler/material tuple")
    return material


def _prebinding(fields: Mapping[str, object], material: Mapping[str, object]) -> Mapping[str, object]:
    header, binding_schema, wrapper, cap = _completion_tuple(material)
    expected = frozenset({"attempt_id", "calculation_plan_id", "calculation_plan_revision", "program_execution_spec_id", "program_execution_spec_payload_sha256", "project_physical_binding_id", "resolved_resource_request_id", "resolved_server_profile_id", "workspace_binding_id", "cwd_binding"})
    _closed(fields, expected, "snapshot prebinding fields")
    source = wrapper.encode("utf-8")
    return freeze_mapping({**fields, "binding_schema": binding_schema, "wrapper_source_sha256": sha256(source).hexdigest(), "wrapper_source_size_bytes": len(source), "rendering_material_sha256": semantic_sha256(material)}, "completion prebinding")


def _render_completion_scheduler(spec, resources, profile, fields, material):
    material = _validate_material(material, profile)
    header, binding_schema, wrapper, cap = _completion_tuple(material)
    _validate_publisher_invocation(material, spec, resources)
    binding = _prebinding(fields, material)
    deployment = _deployment_projection(_unbase64(material["deployment_manifest_base64"], 1024 * 1024))
    config = {
        "prebinding": binding, "prebinding_sha256": semantic_sha256(binding),
        "spec": spec.semantic_payload(), "material": material,
        "xtb_data_path": profile.platform_paths["xtb_data_path"],
        "cores": resources.cores, "walltime_seconds": resources.walltime_seconds,
    }
    lines = ["#!/bin/bash", header, _DATA_LINE + base64.b64encode(_receipt_json(material)).decode("ascii"),
        f"#PBS -l nodes=1:ppn={resources.cores}", f"#PBS -l mem={resources.memory_mb}mb", f"#PBS -l walltime={resources.walltime_seconds}"]
    if resources.queue is not None:
        lines.append(f"#PBS -q {resources.queue}")
    arguments = (deployment["trust_roots"]["server_python"]["path"], "-I", "-S", "-B", "-c", wrapper)
    encoded_config = base64.b64encode(_receipt_json(config)).decode("ascii")
    if material["schema"] == _PILOT_MATERIAL_SCHEMA:
        if len(encoded_config) > 8 * 1024 * 1024 or len(wrapper.encode("utf-8")) > 65536:
            raise _CompletionValueError("publisher fixed source/config launch cap")
        lines.append("exec " + " ".join(shlex.quote(str(x)) for x in arguments) + " <<'AUTO_G16_PUBLISHER_CONFIG'")
        lines.extend((encoded_config, "AUTO_G16_PUBLISHER_CONFIG"))
    else:
        lines.append("exec " + " ".join(shlex.quote(str(x)) for x in (*arguments, encoded_config)))
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

# R4 qualification is private data. Neither this grammar nor a matching digest
# establishes installation provenance, human acceptance, or live authority.
_Q_NAME = "v31-publisher-qualification-v1.json"
_Q_SCHEMA = "auto-g16-v31-publisher-qualification/1"
_Q_CAP = 1024 * 1024
_PILOT_MATERIAL_SCHEMA = "v31-completion-rendering-material/2"
# Original accepted packet, independent of its derived repository link spelling.
_PUBLISHER_CONTRACT_SHA256 = "12ccdebb10b4f1770910e7a0dafe7c74fee99332a4e1ffa7b2cf68c2b8c03c06"
_Q_ROLES = ("workspace-root", "server-python", "xtb", "xtb-data-root")
_PROFILE_BASIS_FIELDS = frozenset({"server_profile_id", "profile_revision", "transport_kind", "target_identity", "remote_user", "remote_root", "platform_paths", "ordered_config_content", "runtime_identities", "effective_config_sha256"})


def _q_text(value, label, cap=256):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= cap or value.strip() != value or any(c in value for c in "\x00\r\n") or value == "NOT_ACQUIRED":
        raise _CompletionValueError(label + ": invalid text")
    return value


def _q_path(value):
    _q_text(value, "qualification path", 4096)
    if not value.startswith("/") or value != "/" and any(p in {"", ".", ".."} for p in value[1:].split("/")):
        raise _CompletionValueError("qualification path is not canonical absolute POSIX")
    return value


def _q_digest(value):
    item = _closed(value, frozenset({"sha256", "size_bytes"}), "digest")
    require_sha256(item["sha256"], "digest")
    _integer(item["size_bytes"], 1, 2**63 - 1, "digest size")
    return item


def _q_node(value):
    item = _closed(value, frozenset({"device", "inode"}), "node")
    _integer(item["device"], 0, 2**63 - 1, "device")
    _integer(item["inode"], 1, 2**63 - 1, "inode")
    return item


def _q_chain(value, path):
    count = 1 if path == "/" else len(path.split("/")) - 1
    if not isinstance(value, (tuple, list)) or not 1 <= len(value) <= 128 or len(value) != count:
        raise _CompletionValueError("parent chain must cover root through exact parent")
    for entry in value:
        _q_node(entry)


def _q_window(value):
    item = _closed(value, frozenset({"started_at", "finished_at"}), "window")
    for stamp in item.values():
        if type(stamp) is not str or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", stamp) is None:
            raise _CompletionValueError("canonical UTC window required")
        try:
            datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError as exc:
            raise _CompletionValueError("invalid UTC calendar") from exc
    if item["started_at"] > item["finished_at"]:
        raise _CompletionValueError("reversed window")
    return item


def _q_contained_window(value, parent):
    item = _q_window(value)
    if item["started_at"] < parent["started_at"] or item["finished_at"] > parent["finished_at"]:
        raise _CompletionValueError("probe window outside observation window")
    return item


def _q_sorted(value, validate, cap):
    if not isinstance(value, (tuple, list)) or not 1 <= len(value) <= cap:
        raise _CompletionValueError("bounded nonempty set required")
    for item in value:
        validate(item)
    if list(value) != sorted(set(value), key=lambda s: s.encode("utf-8")):
        raise _CompletionValueError("set must be sorted and unique")


def _q_probe(value, case_id, window):
    item = _closed(value, frozenset({"case_id", "outcome", "evidence", "observed_window"}), "probe")
    if item["case_id"] != case_id or item["outcome"] != "PASS":
        raise _CompletionValueError("mandatory probe is missing or not PASS")
    _q_digest(item["evidence"])
    _q_contained_window(item["observed_window"], window)


def _q_mount(value):
    item = _closed(value, frozenset({"mount_id", "device_major", "device_minor", "root", "mount_point", "filesystem_type", "source", "mount_options", "super_options"}), "mount")
    _integer(item["mount_id"], 1, 2**63 - 1, "mount id")
    for key in ("device_major", "device_minor"):
        _integer(item[key], 0, 2**63 - 1, key)
    for key in ("root", "mount_point"):
        _q_path(item[key])
    _q_text(item["filesystem_type"], "filesystem")
    _q_text(item["source"], "mount source", 4096)
    for key in ("mount_options", "super_options"):
        _q_sorted(item[key], lambda x: _q_text(x, key), 64)
    return item


def _q_depth(value, depth=0):
    if depth > 16:
        raise _CompletionValueError("qualification nesting exceeds 16")
    if isinstance(value, Mapping):
        for item in value.values():
            _q_depth(item, depth + 1)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _q_depth(item, depth + 1)
    elif type(value) not in {str, int}:
        raise _CompletionValueError("qualification has an unsupported scalar")


def _decode_publisher_qualification(raw):
    envelope = _closed(_canonical_json_object(raw, _Q_CAP), frozenset({"payload", "payload_sha256"}), "qualification envelope")
    _q_depth(envelope)
    payload = _closed(envelope["payload"], frozenset({"schema", "contract_sha256", "scope", "implementation", "profile_basis_sha256", "runtime", "execution_domain", "hosts", "observation_window", "evidence_manifest_sha256", "controller_probe"}), "qualification payload")
    if payload["schema"] != _Q_SCHEMA or payload["contract_sha256"] != _PUBLISHER_CONTRACT_SHA256:
        raise _CompletionValueError("qualification contract/schema mismatch")
    for key in ("profile_basis_sha256", "evidence_manifest_sha256"):
        require_sha256(payload[key], key)
    scope = _closed(payload["scope"], frozenset({"backend", "program_kind", "adapter_id", "adapter_contract_version", "completion_mode", "operations"}), "qualification scope")
    expected_scope = {"backend": "legacy_rtwin_pbs", "program_kind": "xtb", "adapter_id": "auto-g16-v31-xtb", "adapter_contract_version": 3, "completion_mode": _MODE, "operations": ["optimize", "single-point"]}
    if dict(scope) != expected_scope or type(scope["adapter_contract_version"]) is not int:
        raise _CompletionValueError("qualification scope mismatch")
    impl = _closed(payload["implementation"], frozenset({"commit", "tree", "wrapper_source", "probe_source"}), "implementation")
    for key in ("commit", "tree"):
        if type(impl[key]) is not str or re.fullmatch(r"[0-9a-f]{40}", impl[key]) is None:
            raise _CompletionValueError("invalid source Git identity")
    from ._program_completion_wrapper import _PUBLISHER_WRAPPER_SOURCE, _PUBLISHER_PROBE_SOURCE
    for key, source in (("wrapper_source", _PUBLISHER_WRAPPER_SOURCE), ("probe_source", _PUBLISHER_PROBE_SOURCE)):
        if _q_digest(impl[key]) != {"sha256": sha256(source.encode()).hexdigest(), "size_bytes": len(source.encode())}:
            raise _CompletionValueError("qualification source differs from built-in source")
    runtime = _closed(payload["runtime"], frozenset({"deployment_manifest", "server_python", "xtb", "xtb_runtime_data_manifest"}), "qualification runtime")
    for key in ("deployment_manifest", "xtb_runtime_data_manifest"):
        _q_digest(runtime[key])
    for key in ("server_python", "xtb"):
        entry = _closed(runtime[key], frozenset({"path", "sha256", "size_bytes"}), key)
        _q_path(entry["path"])
        _q_digest({k: entry[k] for k in ("sha256", "size_bytes")})
    domain = _closed(payload["execution_domain"], frozenset({"target_identity_sha256", "remote_user", "remote_root", "queue", "eligible_host_keys", "scheduler_scope_evidence"}), "execution domain")
    require_sha256(domain["target_identity_sha256"], "target identity")
    for key in ("remote_user", "queue"):
        _q_text(domain[key], key)
    _q_path(domain["remote_root"])
    _q_digest(domain["scheduler_scope_evidence"])
    _q_sorted(domain["eligible_host_keys"], lambda x: require_sha256(x, "host key"), 32)
    window = _q_window(payload["observation_window"])
    hosts = payload["hosts"]
    if not isinstance(hosts, (list, tuple)) or not 1 <= len(hosts) <= 32:
        raise _CompletionValueError("eligible host count")
    keys = []
    for host in hosts:
        _closed(host, frozenset({"host_key", "machine_id_sha256", "boot_id", "kernel_release", "architecture", "namespaces", "locations", "observed_window", "identity_evidence", "probes"}), "host")
        require_sha256(host["machine_id_sha256"], "machine id")
        if host["host_key"] != semantic_sha256(freeze_mapping({"machine_id_sha256": host["machine_id_sha256"]}, "host key")):
            raise _CompletionValueError("host key mismatch")
        keys.append(host["host_key"])
        if type(host["boot_id"]) is not str or re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", host["boot_id"]) is None:
            raise _CompletionValueError("boot id is not canonical UUID")
        for key in ("kernel_release", "architecture"):
            _q_text(host[key], key)
        ns = _closed(host["namespaces"], frozenset({"mount", "pid"}), "namespaces")
        for item in ns.values():
            _q_node(item)
        host_window = _q_contained_window(host["observed_window"], window)
        _q_digest(host["identity_evidence"])
        locations = host["locations"]
        if not isinstance(locations, (list, tuple)) or len(locations) != 4:
            raise _CompletionValueError("location inventory")
        for role, loc in zip(_Q_ROLES, locations):
            _closed(loc, frozenset({"role", "path", "parent_chain", "object", "mount", "evidence"}), "location")
            if loc["role"] != role:
                raise _CompletionValueError("location order/role mismatch")
            path = _q_path(loc["path"])
            _q_chain(loc["parent_chain"], path)
            _q_node(loc["object"])
            mount = _q_mount(loc["mount"])
            point = mount["mount_point"]
            if point != "/" and path != point and not path.startswith(point + "/"):
                raise _CompletionValueError("mount does not cover location")
            _q_digest(loc["evidence"])
        expected_paths = (domain["remote_root"], runtime["server_python"]["path"], runtime["xtb"]["path"])
        if tuple(loc["path"] for loc in locations[:3]) != expected_paths:
            raise _CompletionValueError("host/runtime path mismatch")
        probes = host["probes"]
        if not isinstance(probes, (tuple, list)) or len(probes) != 7:
            raise _CompletionValueError("mandatory host probes missing")
        for index, probe in enumerate(probes, 1):
            _q_probe(probe, f"P{index:02d}", host_window)
    if keys != list(domain["eligible_host_keys"]):
        raise _CompletionValueError("host inventory differs from eligible set")
    _q_probe(payload["controller_probe"], "P08", window)
    frozen = freeze_mapping(payload, "qualification payload")
    if envelope["payload_sha256"] != semantic_sha256(frozen):
        raise _CompletionValueError("qualification payload digest mismatch")
    return freeze_mapping(envelope, "qualification")


def _publisher_profile_basis(profile):
    profile.assert_identity_closed()
    original = _closed(profile._identity_payload, _PROFILE_BASIS_FIELDS, "profile identity payload")
    projection = {key: value for key, value in original.items() if key != "effective_config_sha256"}
    projection["runtime_identities"] = {key: value for key, value in original["runtime_identities"].items() if key != _Q_NAME}
    return semantic_sha256(freeze_mapping(projection, "publisher profile basis"))


def _validate_publisher_profile(q, profile, deployment):
    p = q["payload"]
    if p["profile_basis_sha256"] != _publisher_profile_basis(profile):
        raise _CompletionValueError("qualification does not bind complete profile basis")
    runtime, domain = p["runtime"], p["execution_domain"]
    if runtime["deployment_manifest"] != profile.runtime_identities[_DEPLOYMENT_NAME] or runtime["xtb_runtime_data_manifest"] != profile.runtime_identities[_DATA_NAME]:
        raise _CompletionValueError("qualification manifest identity mismatch")
    py = deployment["trust_roots"]["server_python"]
    if runtime["server_python"] != {"path": py["path"], "sha256": py["expected_sha256"], "size_bytes": py["expected_size_bytes"]}:
        raise _CompletionValueError("qualification Python differs from manifest")
    xtb = runtime["xtb"]
    if xtb["path"] != profile.platform_paths["xtb_executable_path"] or {k: xtb[k] for k in ("sha256", "size_bytes")} != profile.runtime_identities.get("xtb"):
        raise _CompletionValueError("qualification xTB differs from profile")
    if (domain["target_identity_sha256"], domain["remote_user"], domain["remote_root"]) != (semantic_sha256(profile.target_identity), profile.remote_user, profile.remote_root):
        raise _CompletionValueError("qualification target differs from profile")
    if any(host["locations"][3]["path"] != profile.platform_paths["xtb_data_path"] for host in p["hosts"]):
        raise _CompletionValueError("qualification runtime data root differs from profile")


def _prepare_publisher_pilot_rendering_material(current_profile, resolved_profile):
    old = _prepare_completion_rendering_material(current_profile, resolved_profile)
    try:
        raw = current_profile.runtime_contents[_Q_NAME]
    except KeyError as exc:
        raise _CompletionValueError("publisher qualification material missing") from exc
    return _validate_material({**old, "schema": _PILOT_MATERIAL_SCHEMA, "publisher_qualification_base64": base64.b64encode(raw).decode("ascii")}, resolved_profile)


def _completion_tuple(material):
    from ._program_completion_wrapper import _WRAPPER_SOURCE, _PUBLISHER_WRAPPER_SOURCE
    if not isinstance(material, Mapping):
        raise _CompletionValueError("material required for tuple dispatch")
    if material.get("schema") == _MATERIAL_SCHEMA and set(material) == _MATERIAL_FIELDS:
        return "# auto-g16-v31-scheduler/2", "v31-completion-prebinding/2", _WRAPPER_SOURCE, 3 * _Q_CAP
    if material.get("schema") == _PILOT_MATERIAL_SCHEMA and set(material) == _MATERIAL_FIELDS | {"publisher_qualification_base64"}:
        return "# auto-g16-v31-scheduler/3", "v31-completion-prebinding/3", _PUBLISHER_WRAPPER_SOURCE, 5 * _Q_CAP
    raise _CompletionValueError("unknown/mixed completion tuple")


def _validate_publisher_invocation(material, spec, resources):
    if material["schema"] == _PILOT_MATERIAL_SCHEMA:
        q = _decode_publisher_qualification(_unbase64(material["publisher_qualification_base64"], _Q_CAP))["payload"]
        executable = spec.invocation["executable_identity"]
        if resources.queue != q["execution_domain"]["queue"] or q["runtime"]["xtb"] != {"path": executable["absolute_path"], "sha256": executable["sha256"], "size_bytes": executable["size_bytes"]}:
            raise _CompletionValueError("pilot queue/invocation differs from qualification")
