"""Offline import of one explicit, verified RTwin log/input/sidecar capture.

Writes only a NEW local index. No remote access, Core store or approval writes.
The public Result parser's required envelope identifiers are local parsing
context only, never claims of original Core bindings or execution snapshots.
"""
from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path, PureWindowsPath

from auto_g16.result import GaussianJobParser, OutputArtifact, OutputEnvelope
from .archive import AUTHORITY, SCHEMA, read_pinned, validate_index


def plain(value):
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def build_archive_evidence(capture: dict) -> tuple[dict, dict]:
    if capture.get("schema") != "rtwin-archive-capture/1" or capture.get("source") != "rtwin-local":
        raise ValueError("unsupported capture")
    files = capture["files"]
    if len(files) != 3:
        raise ValueError("one log, input and job.json required")
    source_paths = [PureWindowsPath(f["path"]) for f in files]
    if (any(not p.is_absolute() or ".." in p.parts or str(p) != f["path"] for p, f in zip(source_paths, files))
            or len({str(p.parent).casefold() for p in source_paths}) != 1):
        raise ValueError("capture must contain canonical sibling Windows files")
    contents, artifacts = {}, []
    for f in files:
        name = f["path"].rsplit("\\", 1)[-1]
        role = "log" if name.endswith(".log") else "input" if name.endswith((".gjf", ".com")) else "legacy_metadata" if name == "job.json" else None
        if role is None or role in contents or f["sha256"] != f["sha256_after"] or f["size"] > 1024 * 1024:
            raise ValueError("invalid or changing capture")
        b = read_pinned(Path(f["local_file"]), f["sha256"])
        if len(b) != f["size"]:
            raise ValueError("capture size mismatch")
        contents[role] = b
        artifacts.append({"role": role, "logical_name": name, "sha256": f["sha256"], "size_bytes": len(b)})
    a = {f["role"]: f for f in artifacts}
    job = json.loads(contents["legacy_metadata"])
    if (job.get("schema") != "codex-gaussian-pbs/1" or job.get("input_sha256") != a["input"]["sha256"]
            or job.get("result", {}).get("log") != a["log"]["logical_name"]):
        raise ValueError("legacy sidecar does not bind selected input/log")
    identity = "archive-" + a["log"]["sha256"]
    manifest_hash = sha256(json.dumps(artifacts, sort_keys=True).encode()).hexdigest()
    envelope = OutputEnvelope(
        attempt_id=identity, input_binding_observation_id="archive-unbound-input",
        execution_snapshot_id="archive-no-execution-snapshot", capture_source_id="archive-rtwin",
        capture_sequence=1, capture_status="captured", capture_completeness="complete",
        artifacts=(OutputArtifact(artifact_kind="gaussian-log", logical_name=a["log"]["logical_name"],
                                  sha256=a["log"]["sha256"], size_bytes=a["log"]["size_bytes"]),),
        capture_manifest_sha256=manifest_hash, captured_at_utc=capture["observed_at"])
    parser = GaussianJobParser()
    outcome = parser.parse(envelope, {a["log"]["logical_name"]: contents["log"]})
    facts = plain(outcome.facts)
    summary = None
    if outcome.parse_status.value == "parsed":
        n = facts["frequency_count"]
        summary = {"termination": facts["program_status"], "normal_count": facts["normal_termination_count"],
                   "error_count": facts["error_termination_count"], "energy_hartree": facts["final_energy_hartree"],
                   "optimization": facts["optimization_completed_marker"], "stationary_point": facts["stationary_point_marker"],
                   "frequency_count": n if n else None, "imaginary_count": facts["imaginary_frequency_count"] if n else None}
    record = {
        "archive_id": identity, "title": job["project"], "source_kind": "legacy_archive",
        "source_location": "RTwin 本地归档", "captured_at": capture["observed_at"],
        "artifacts": artifacts, "input": {"text": contents["input"].decode("utf-8"), "binding": "legacy-job-input-hash-matched"},
        "legacy_metadata": {"schema": job["schema"], "recorded_status": job["status"], "scope": "historical-sidecar-claim"},
        "parser": {"name": parser.parser_name, "version": parser.parser_version,
                   "status": outcome.parse_status.value, "diagnostics": list(outcome.diagnostics)},
        "summary": summary, "authority": dict(AUTHORITY),
    }
    validate_index({"schema": SCHEMA, "records": [record]})
    return record, plain(outcome.payload())


def build_record(capture: dict) -> dict:
    return build_archive_evidence(capture)[0]


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capture", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    record = build_record(json.loads(args.capture.read_text()))
    raw = (json.dumps({"schema": SCHEMA, "records": [record]}, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with args.output.open("xb") as f:
        f.write(raw)
    print(json.dumps({"records": 1, "sha256": sha256(raw).hexdigest(), "parser_status": record["parser"]["status"]}))


if __name__ == "__main__":
    main()
