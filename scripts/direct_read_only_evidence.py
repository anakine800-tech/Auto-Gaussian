#!/usr/bin/env python3
"""Pure ``pbs_legacy_v1`` qstat parsing and direct evidence projections.

The module accepts only already-collected bytes and explicit timestamps.  It
does not acquire those bytes and contains no transport, SSH, shell, command,
callback, retry, fetch, materialization, PBS effect, Gaussian, or filesystem
implementation.  Every portable document is read-only and non-authorizing.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


QSTAT_EVIDENCE_SCHEMA = "gaussian-direct-qstat-evidence-core/1"
TERMINAL_RECEIPT_SCHEMA = "gaussian-scheduler-terminal-evidence-receipt/1"
OWNER = "auto-g16-direct-read-only-evidence-owner"
OWNER_VERSION = "direct-read-only-evidence-core/1"
PARSER_VERSION = "pbs_legacy_v1-qstat-single-job/1"
BACKEND_KIND = "direct_ssh_pbs"
TRANSPORT_KIND = "direct_ssh"
TOPOLOGY = "direct_one_hop"
SCHEDULER_DIALECT = "pbs_legacy_v1"
MAX_QSTAT_OUTPUT_BYTES = 64 * 1024
MAX_FRESH_AGE_SECONDS = 120
UNKNOWN_JOB_RETURN_CODE = 153
ZERO_SHA = "0" * 64
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
JOB_ID_RE = re.compile(r"^[1-9][0-9]{0,19}\.[A-Za-z0-9][A-Za-z0-9.-]{0,127}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
FIELD_RE = re.compile(r"^    ([A-Za-z][A-Za-z0-9_.]*) = ([^\x00-\x1f\x7f]+)$")
DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]{0,19})$")
RETURN_CODE_RE = re.compile(r"^(?:0|-?[1-9][0-9]{0,9})$")

# Closed grammar for one ``qstat -f <exact-id>`` block.  A server extension is
# unknown evidence until this list and its tests receive a separate review.
ALLOWED_QSTAT_FIELDS = frozenset(
    {
        "Checkpoint",
        "Error_Path",
        "Hold_Types",
        "Job_Name",
        "Job_Owner",
        "Join_Path",
        "Keep_Files",
        "Mail_Points",
        "Output_Path",
        "Priority",
        "Rerunable",
        "Resource_List.mem",
        "Resource_List.ncpus",
        "Resource_List.nodect",
        "Resource_List.nodes",
        "Resource_List.walltime",
        "Variable_List",
        "comment",
        "ctime",
        "etime",
        "exec_host",
        "exec_vnode",
        "exit_status",
        "job_state",
        "mtime",
        "qtime",
        "queue",
        "resources_used.cput",
        "resources_used.mem",
        "resources_used.vmem",
        "resources_used.walltime",
        "server",
        "session_id",
        "start_count",
        "start_time",
        "submit_args",
    }
)
REQUIRED_QSTAT_FIELDS = frozenset({"Job_Name", "job_state"})
PBS_STATE_TO_LIFECYCLE = {
    "Q": "queued",
    "R": "running",
    "H": "held",
    "E": "exiting",
    "C": "terminal",
    "F": "terminal",
}
UNKNOWN_REASONS = frozenset(
    {
        "timeout",
        "incomplete_eof",
        "output_too_large",
        "invalid_utf8",
        "unexpected_returncode",
        "unexpected_streams",
        "unknown_job_message_mismatch",
        "malformed_qstat",
        "job_id_mismatch",
        "job_name_mismatch",
    }
)
AUTHORITY = {
    "read_only": True,
    "portable_projection": True,
    "authorizes_effect": False,
    "scientific_acceptance": False,
    "production_supported": False,
    "transport_implemented": False,
    "remote_effect_performed": False,
    "automatic_retry": False,
}
TOPOLOGY_PROJECTION = {
    "topology": TOPOLOGY,
    "hop_count": "1",
    "backend_kind": BACKEND_KIND,
    "transport_kind": TRANSPORT_KIND,
    "scheduler_dialect": SCHEDULER_DIALECT,
}


class DirectReadOnlyEvidenceError(ValueError):
    """The supplied bytes or portable evidence fail the closed contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectReadOnlyEvidenceError(message)


def canonical_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DirectReadOnlyEvidenceError(
            f"value is not canonical JSON: {exc}"
        ) from exc
    return (encoded + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _finalize(document: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result[field] = ""
    result[field] = digest(result)
    return result


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields differ")
    return value


def _sha(value: Any, label: str, *, allow_empty_digest: bool = False) -> str:
    _require(
        type(value) is str
        and SHA_RE.fullmatch(value) is not None
        and value != ZERO_SHA,
        f"{label} must be a lowercase nonzero SHA-256",
    )
    if not allow_empty_digest:
        _require(
            value != hashlib.sha256(b"").hexdigest(),
            f"{label} must not bind empty bytes",
        )
    return value


def _timestamp(value: Any, label: str) -> datetime:
    _require(
        type(value) is str and TIMESTAMP_RE.fullmatch(value) is not None,
        f"{label} must be canonical UTC microsecond time",
    )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise DirectReadOnlyEvidenceError(f"{label} is not a real UTC time") from exc
    _require(
        parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == value,
        f"{label} is not canonical UTC time",
    )
    return parsed


def _job_id(value: Any) -> str:
    _require(
        type(value) is str and JOB_ID_RE.fullmatch(value) is not None,
        "job_id is not one exact PBS job identifier",
    )
    return value


def _strict_utf8(raw: bytes, label: str) -> str:
    _require(type(raw) is bytes, f"{label} must be exact bytes")
    _require(not raw.startswith(b"\xef\xbb\xbf"), f"{label} contains a UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DirectReadOnlyEvidenceError(f"{label} is not strict UTF-8") from exc
    _require("\r" not in text and "\x00" not in text, f"{label} contains forbidden controls")
    return text


def parse_qstat_single_job(raw: bytes, expected_job_id: str) -> dict[str, Any]:
    """Parse one bounded, strict-UTF-8, closed-grammar qstat job block."""

    expected_job_id = _job_id(expected_job_id)
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_QSTAT_OUTPUT_BYTES, "qstat output size differs")
    text = _strict_utf8(raw, "qstat stdout")
    _require(text.endswith("\n"), "qstat block must end with one LF")
    lines = text[:-1].split("\n")
    _require(len(lines) >= 3 and all(lines), "qstat block is empty or contains blank lines")
    header = lines[0]
    prefix = "Job Id: "
    _require(header.startswith(prefix), "qstat block header is malformed")
    parsed_job_id = header[len(prefix) :]
    _require(JOB_ID_RE.fullmatch(parsed_job_id) is not None, "qstat block job id is malformed")
    _require(parsed_job_id == expected_job_id, "qstat block job id differs")
    _require(sum(line.startswith(prefix) for line in lines) == 1, "qstat output contains multiple job blocks")

    fields: dict[str, str] = {}
    for line in lines[1:]:
        match = FIELD_RE.fullmatch(line)
        _require(match is not None, "qstat field line is malformed or continued")
        key, value = match.groups()
        _require(key in ALLOWED_QSTAT_FIELDS, f"qstat field is outside the closed grammar: {key}")
        _require(key not in fields, f"qstat field repeats: {key}")
        _require(value == value.strip(), f"qstat field value is not trimmed: {key}")
        fields[key] = value
    _require(REQUIRED_QSTAT_FIELDS <= set(fields), "qstat block lacks required fields")
    _require(PROJECT_RE.fullmatch(fields["Job_Name"]) is not None, "qstat Job_Name is malformed")
    _require(fields["job_state"] in PBS_STATE_TO_LIFECYCLE, "qstat job_state is unsupported")
    if "session_id" in fields:
        _require(
            re.fullmatch(r"[1-9][0-9]{0,18}", fields["session_id"]) is not None,
            "qstat session_id is malformed",
        )
    return {
        "job_id": parsed_job_id,
        "job_name": fields["Job_Name"],
        "pbs_state": fields["job_state"],
        "lifecycle": PBS_STATE_TO_LIFECYCLE[fields["job_state"]],
        "session_id": fields.get("session_id"),
        "fields": copy.deepcopy(fields),
    }


@dataclass(frozen=True, slots=True)
class QstatClassification:
    status: str
    record_present: bool | None
    job_id: str | None
    job_name: str | None
    pbs_state: str | None
    lifecycle: str
    session_id: str | None
    returncode: int | None
    reason: str | None
    stdout_sha256: str
    stdout_size_bytes: int
    stderr_sha256: str
    stderr_size_bytes: int

    def document(self) -> dict[str, Any]:
        return {
            "parser": PARSER_VERSION,
            "status": self.status,
            "record_present": self.record_present,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "pbs_state": self.pbs_state,
            "lifecycle": self.lifecycle,
            "session_id": self.session_id,
            "returncode": None if self.returncode is None else str(self.returncode),
            "reason": self.reason,
            "stdout_sha256": self.stdout_sha256,
            "stdout_size_bytes": str(self.stdout_size_bytes),
            "stderr_sha256": self.stderr_sha256,
            "stderr_size_bytes": str(self.stderr_size_bytes),
        }


def _classification(
    *,
    stdout: bytes,
    stderr: bytes,
    returncode: int | None,
    status: str = "unknown",
    record_present: bool | None = None,
    job_id: str | None = None,
    job_name: str | None = None,
    pbs_state: str | None = None,
    lifecycle: str = "unknown",
    session_id: str | None = None,
    reason: str | None = None,
) -> QstatClassification:
    return QstatClassification(
        status=status,
        record_present=record_present,
        job_id=job_id,
        job_name=job_name,
        pbs_state=pbs_state,
        lifecycle=lifecycle,
        session_id=session_id,
        returncode=returncode,
        reason=reason,
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stdout_size_bytes=len(stdout),
        stderr_sha256=hashlib.sha256(stderr).hexdigest(),
        stderr_size_bytes=len(stderr),
    )


def classify_qstat_bytes(
    *,
    expected_job_id: str,
    expected_job_name: str,
    returncode: int | None,
    stdout: bytes,
    stderr: bytes,
    timed_out: bool,
    eof_complete: bool,
) -> QstatClassification:
    """Classify pre-collected qstat bytes without acquiring or executing them."""

    expected_job_id = _job_id(expected_job_id)
    _require(
        type(expected_job_name) is str
        and PROJECT_RE.fullmatch(expected_job_name) is not None,
        "expected job name is malformed",
    )
    _require(type(stdout) is bytes and type(stderr) is bytes, "qstat streams must be bytes")
    _require(type(timed_out) is bool and type(eof_complete) is bool, "qstat completion flags differ")
    _require(
        returncode is None or (type(returncode) is int and -(2**31) <= returncode < 2**31),
        "qstat returncode differs",
    )
    if len(stdout) + len(stderr) > MAX_QSTAT_OUTPUT_BYTES:
        return _classification(stdout=stdout, stderr=stderr, returncode=returncode, reason="output_too_large")
    if timed_out:
        return _classification(stdout=stdout, stderr=stderr, returncode=returncode, reason="timeout")
    if not eof_complete:
        return _classification(stdout=stdout, stderr=stderr, returncode=returncode, reason="incomplete_eof")
    try:
        _strict_utf8(stdout, "qstat stdout")
        _strict_utf8(stderr, "qstat stderr")
    except DirectReadOnlyEvidenceError:
        return _classification(stdout=stdout, stderr=stderr, returncode=returncode, reason="invalid_utf8")

    if returncode == 0:
        if not stdout or stderr:
            return _classification(stdout=stdout, stderr=stderr, returncode=returncode, reason="unexpected_streams")
        try:
            parsed = parse_qstat_single_job(stdout, expected_job_id)
        except DirectReadOnlyEvidenceError as exc:
            reason = "job_id_mismatch" if "job id differs" in str(exc) else "malformed_qstat"
            return _classification(stdout=stdout, stderr=stderr, returncode=returncode, reason=reason)
        if parsed["job_name"] != expected_job_name:
            return _classification(stdout=stdout, stderr=stderr, returncode=returncode, reason="job_name_mismatch")
        return _classification(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            status="present",
            record_present=True,
            job_id=parsed["job_id"],
            job_name=parsed["job_name"],
            pbs_state=parsed["pbs_state"],
            lifecycle=parsed["lifecycle"],
            session_id=parsed["session_id"],
        )

    absent = f"qstat: Unknown Job Id {expected_job_id}\n".encode("utf-8")
    if returncode == UNKNOWN_JOB_RETURN_CODE and stdout == b"" and stderr == absent:
        return _classification(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            status="absent",
            record_present=False,
            lifecycle="absent",
        )
    reason = (
        "unknown_job_message_mismatch"
        if b"Unknown Job" in stdout or b"Unknown Job" in stderr
        else "unexpected_returncode"
    )
    return _classification(stdout=stdout, stderr=stderr, returncode=returncode, reason=reason)


@dataclass(frozen=True, slots=True)
class DirectJobBinding:
    project: str
    job_id: str
    attempt_id: str
    input_sha256: str
    direct_binding_sha256: str

    def __post_init__(self) -> None:
        _require(type(self.project) is str and PROJECT_RE.fullmatch(self.project) is not None, "binding project differs")
        _job_id(self.job_id)
        _require(type(self.attempt_id) is str and ATTEMPT_RE.fullmatch(self.attempt_id) is not None, "binding attempt differs")
        _sha(self.input_sha256, "binding input_sha256")
        _sha(self.direct_binding_sha256, "binding direct_binding_sha256")

    def document(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "input_sha256": self.input_sha256,
            "direct_binding_sha256": self.direct_binding_sha256,
        }


@dataclass(frozen=True, slots=True)
class QstatObservation:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    eof_complete: bool
    requested_at: str
    collected_at: str
    received_at: str


@dataclass(frozen=True, slots=True)
class DirectQstatEvidence:
    _bytes: bytes

    def document(self) -> dict[str, Any]:
        try:
            value = json.loads(self._bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DirectReadOnlyEvidenceError("qstat evidence wrapper bytes differ") from exc
        return validate_qstat_evidence(value)


@dataclass(frozen=True, slots=True)
class TerminalReceipt:
    _bytes: bytes

    def document(self, evidence: DirectQstatEvidence | dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            value = json.loads(self._bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DirectReadOnlyEvidenceError("terminal receipt wrapper bytes differ") from exc
        return validate_terminal_receipt(value, evidence=evidence)


def _freshness(
    requested_at: str,
    collected_at: str,
    received_at: str,
    maximum_age_seconds: int,
) -> tuple[str, int | None]:
    requested = _timestamp(requested_at, "requested_at")
    collected = _timestamp(collected_at, "collected_at")
    received = _timestamp(received_at, "received_at")
    _require(
        type(maximum_age_seconds) is int
        and 1 <= maximum_age_seconds <= MAX_FRESH_AGE_SECONDS,
        "maximum age differs",
    )
    if not requested <= collected <= received:
        return "unknown", None
    elapsed = received - collected
    age = elapsed.days * 86_400 + elapsed.seconds + (1 if elapsed.microseconds else 0)
    return (
        "fresh" if elapsed <= timedelta(seconds=maximum_age_seconds) else "stale"
    ), age


def build_qstat_evidence(
    binding: DirectJobBinding,
    observation: QstatObservation,
    *,
    maximum_age_seconds: int = MAX_FRESH_AGE_SECONDS,
) -> DirectQstatEvidence:
    """Build one immutable non-authorizing projection from pre-collected bytes."""

    _require(type(binding) is DirectJobBinding, "exact direct job binding is required")
    _require(type(observation) is QstatObservation, "exact qstat observation is required")
    classification = classify_qstat_bytes(
        expected_job_id=binding.job_id,
        expected_job_name=binding.project,
        returncode=observation.returncode,
        stdout=observation.stdout,
        stderr=observation.stderr,
        timed_out=observation.timed_out,
        eof_complete=observation.eof_complete,
    )
    freshness, age_seconds = _freshness(
        observation.requested_at,
        observation.collected_at,
        observation.received_at,
        maximum_age_seconds,
    )
    state = classification.lifecycle if freshness == "fresh" else "unknown"
    terminal_eligible = state == "terminal"
    qstat = classification.document()
    qstat["observation_payload_sha256"] = digest(qstat)
    document = _finalize(
        {
            "schema": QSTAT_EVIDENCE_SCHEMA,
            "owner": OWNER,
            "owner_version": OWNER_VERSION,
            "topology": copy.deepcopy(TOPOLOGY_PROJECTION),
            "binding": binding.document(),
            "collection": {
                "mode": "precollected_bytes_only",
                "requested_at": observation.requested_at,
                "collected_at": observation.collected_at,
                "received_at": observation.received_at,
                "maximum_age_seconds": str(maximum_age_seconds),
                "age_seconds": None if age_seconds is None else str(age_seconds),
                "freshness": freshness,
            },
            "qstat": qstat,
            "state": state,
            "terminal_receipt_eligible": terminal_eligible,
            "authority": copy.deepcopy(AUTHORITY),
            "qstat_evidence_sha256": "",
        },
        "qstat_evidence_sha256",
    )
    validate_qstat_evidence(document)
    return DirectQstatEvidence(canonical_bytes(document))


def _validate_topology(value: Any) -> dict[str, Any]:
    topology = _exact(
        value,
        {"topology", "hop_count", "backend_kind", "transport_kind", "scheduler_dialect"},
        "topology",
    )
    _require(topology == TOPOLOGY_PROJECTION, "direct one-hop topology differs")
    return topology


def _validate_binding(value: Any) -> dict[str, Any]:
    binding = _exact(
        value,
        {"project", "job_id", "attempt_id", "input_sha256", "direct_binding_sha256"},
        "binding",
    )
    DirectJobBinding(**binding)
    return binding


def _validate_authority(value: Any) -> dict[str, Any]:
    authority = _exact(value, set(AUTHORITY), "authority")
    _require(authority == AUTHORITY, "portable authority boundary differs")
    return authority


def _validate_qstat(value: Any, binding: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "parser",
        "status",
        "record_present",
        "job_id",
        "job_name",
        "pbs_state",
        "lifecycle",
        "session_id",
        "returncode",
        "reason",
        "stdout_sha256",
        "stdout_size_bytes",
        "stderr_sha256",
        "stderr_size_bytes",
        "observation_payload_sha256",
    }
    qstat = _exact(value, fields, "qstat evidence")
    _require(qstat["parser"] == PARSER_VERSION, "qstat parser version differs")
    for name in ("stdout_sha256", "stderr_sha256"):
        _sha(qstat[name], f"qstat {name}", allow_empty_digest=True)
    sizes: dict[str, int] = {}
    for name in ("stdout_size_bytes", "stderr_size_bytes"):
        _require(
            type(qstat[name]) is str and DECIMAL_RE.fullmatch(qstat[name]) is not None,
            f"qstat {name} differs",
        )
        sizes[name] = int(qstat[name])
    _require(
        qstat["returncode"] is None
        or (type(qstat["returncode"]) is str and RETURN_CODE_RE.fullmatch(qstat["returncode"]) is not None),
        "qstat returncode differs",
    )
    _require(
        sizes["stdout_size_bytes"] + sizes["stderr_size_bytes"]
        <= MAX_QSTAT_OUTPUT_BYTES
        or qstat["reason"] == "output_too_large",
        "qstat bounded-size relation differs",
    )
    status = qstat["status"]
    empty_stream_sha256 = hashlib.sha256(b"").hexdigest()
    if status == "present":
        expected_lifecycle = PBS_STATE_TO_LIFECYCLE.get(qstat["pbs_state"])
        _require(
            qstat["record_present"] is True
            and qstat["job_id"] == binding["job_id"]
            and qstat["job_name"] == binding["project"]
            and expected_lifecycle is not None
            and qstat["lifecycle"] == expected_lifecycle
            and qstat["returncode"] == "0"
            and qstat["reason"] is None,
            "present qstat evidence differs",
        )
        _require(
            1 <= sizes["stdout_size_bytes"] <= MAX_QSTAT_OUTPUT_BYTES
            and sizes["stderr_size_bytes"] == 0
            and qstat["stdout_sha256"] != empty_stream_sha256
            and qstat["stderr_sha256"] == empty_stream_sha256,
            "present qstat stream evidence differs",
        )
        _require(
            qstat["session_id"] is None
            or (type(qstat["session_id"]) is str and re.fullmatch(r"[1-9][0-9]{0,18}", qstat["session_id"]) is not None),
            "present qstat session differs",
        )
    elif status == "absent":
        absent_stderr = f"qstat: Unknown Job Id {binding['job_id']}\n".encode("utf-8")
        _require(
            qstat["record_present"] is False
            and all(qstat[name] is None for name in ("job_id", "job_name", "pbs_state", "session_id"))
            and qstat["lifecycle"] == "absent"
            and qstat["returncode"] == str(UNKNOWN_JOB_RETURN_CODE)
            and qstat["reason"] is None,
            "absent qstat evidence differs",
        )
        _require(
            sizes["stdout_size_bytes"] == 0
            and qstat["stdout_sha256"] == empty_stream_sha256
            and sizes["stderr_size_bytes"] == len(absent_stderr)
            and qstat["stderr_sha256"] == hashlib.sha256(absent_stderr).hexdigest(),
            "absent qstat stream evidence differs",
        )
    elif status == "unknown":
        _require(
            qstat["record_present"] is None
            and all(qstat[name] is None for name in ("job_id", "job_name", "pbs_state", "session_id"))
            and qstat["lifecycle"] == "unknown"
            and qstat["reason"] in UNKNOWN_REASONS,
            "unknown qstat evidence differs",
        )
    else:
        raise DirectReadOnlyEvidenceError("qstat evidence status differs")
    projection = copy.deepcopy(qstat)
    claimed = projection.pop("observation_payload_sha256")
    _sha(claimed, "qstat observation_payload_sha256")
    _require(digest(projection) == claimed, "qstat observation hash differs")
    return qstat


def validate_qstat_evidence(value: Any) -> dict[str, Any]:
    fields = {
        "schema",
        "owner",
        "owner_version",
        "topology",
        "binding",
        "collection",
        "qstat",
        "state",
        "terminal_receipt_eligible",
        "authority",
        "qstat_evidence_sha256",
    }
    document = _exact(value, fields, "direct qstat evidence")
    _require(
        document["schema"] == QSTAT_EVIDENCE_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION,
        "direct qstat evidence owner differs",
    )
    _validate_topology(document["topology"])
    binding = _validate_binding(document["binding"])
    collection = _exact(
        document["collection"],
        {"mode", "requested_at", "collected_at", "received_at", "maximum_age_seconds", "age_seconds", "freshness"},
        "collection",
    )
    _require(collection["mode"] == "precollected_bytes_only", "collection mode differs")
    _require(
        type(collection["maximum_age_seconds"]) is str
        and DECIMAL_RE.fullmatch(collection["maximum_age_seconds"]) is not None,
        "collection maximum age differs",
    )
    _require(
        collection["age_seconds"] is None
        or (
            type(collection["age_seconds"]) is str
            and DECIMAL_RE.fullmatch(collection["age_seconds"]) is not None
        ),
        "collection age differs",
    )
    expected_freshness, expected_age_value = _freshness(
        collection["requested_at"],
        collection["collected_at"],
        collection["received_at"],
        int(collection["maximum_age_seconds"]),
    )
    expected_age = None if expected_age_value is None else str(expected_age_value)
    _require(
        collection["freshness"] == expected_freshness
        and collection["age_seconds"] == expected_age,
        "collection freshness differs",
    )
    qstat = _validate_qstat(document["qstat"], binding)
    expected_state = qstat["lifecycle"] if expected_freshness == "fresh" else "unknown"
    _require(document["state"] == expected_state, "qstat evidence state differs")
    _require(
        type(document["terminal_receipt_eligible"]) is bool
        and document["terminal_receipt_eligible"] is (expected_state == "terminal"),
        "terminal eligibility differs",
    )
    _validate_authority(document["authority"])
    projection = copy.deepcopy(document)
    projection["qstat_evidence_sha256"] = ""
    _sha(document["qstat_evidence_sha256"], "qstat evidence hash")
    _require(digest(projection) == document["qstat_evidence_sha256"], "qstat evidence hash differs")
    return copy.deepcopy(document)


def build_terminal_receipt(evidence: DirectQstatEvidence) -> TerminalReceipt:
    """Bind one fresh C/F scheduler observation; grant no effect or science."""

    _require(type(evidence) is DirectQstatEvidence, "exact qstat evidence wrapper is required")
    source = evidence.document()
    _require(source["terminal_receipt_eligible"] is True, "qstat evidence is not fresh scheduler-terminal evidence")
    document = _finalize(
        {
            "schema": TERMINAL_RECEIPT_SCHEMA,
            "owner": OWNER,
            "owner_version": OWNER_VERSION,
            "topology": copy.deepcopy(source["topology"]),
            "binding": copy.deepcopy(source["binding"]),
            "terminal_state": "scheduler_terminal",
            "pbs_state": source["qstat"]["pbs_state"],
            "collected_at": source["collection"]["collected_at"],
            "qstat_evidence_sha256": source["qstat_evidence_sha256"],
            "authority": copy.deepcopy(AUTHORITY),
            "receipt_sha256": "",
        },
        "receipt_sha256",
    )
    validate_terminal_receipt(document, evidence=source)
    return TerminalReceipt(canonical_bytes(document))


def validate_terminal_receipt(
    value: Any,
    *,
    evidence: DirectQstatEvidence | dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = {
        "schema",
        "owner",
        "owner_version",
        "topology",
        "binding",
        "terminal_state",
        "pbs_state",
        "collected_at",
        "qstat_evidence_sha256",
        "authority",
        "receipt_sha256",
    }
    document = _exact(value, fields, "terminal receipt")
    _require(
        document["schema"] == TERMINAL_RECEIPT_SCHEMA
        and document["owner"] == OWNER
        and document["owner_version"] == OWNER_VERSION,
        "terminal receipt owner differs",
    )
    _validate_topology(document["topology"])
    _validate_binding(document["binding"])
    _require(
        document["terminal_state"] == "scheduler_terminal"
        and document["pbs_state"] in {"C", "F"},
        "terminal receipt state differs",
    )
    _timestamp(document["collected_at"], "terminal collected_at")
    _sha(document["qstat_evidence_sha256"], "terminal qstat evidence hash")
    _validate_authority(document["authority"])
    projection = copy.deepcopy(document)
    projection["receipt_sha256"] = ""
    _sha(document["receipt_sha256"], "terminal receipt hash")
    _require(digest(projection) == document["receipt_sha256"], "terminal receipt hash differs")
    if evidence is not None:
        source = evidence.document() if type(evidence) is DirectQstatEvidence else validate_qstat_evidence(evidence)
        _require(
            source["terminal_receipt_eligible"] is True
            and source["qstat"]["pbs_state"] == document["pbs_state"]
            and source["collection"]["collected_at"] == document["collected_at"]
            and source["qstat_evidence_sha256"] == document["qstat_evidence_sha256"]
            and source["topology"] == document["topology"]
            and source["binding"] == document["binding"],
            "terminal receipt and qstat evidence binding differ",
        )
    return copy.deepcopy(document)
