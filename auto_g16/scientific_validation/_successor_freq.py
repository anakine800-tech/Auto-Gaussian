"""Private fact-only Freq assessment; no parsing, persistence or V30 outcome."""
from collections.abc import Mapping
from math import isfinite
from auto_g16.result.models import CaptureCompleteness, ParseStatus
from .models import ScientificValidationError

POLICY = "v31-successor-two-stage-minimum/1"


def _require(value, reason):
    if not value:
        raise ScientificValidationError(reason)


def assess_frequency(envelope, parsed, expected_geometry):
    """Assess a single Freq capture against a separately proven Opt geometry.

    The composition owner must close both sources first. This function never
    adds Opt markers to Freq facts or constructs a public minimum outcome.
    """
    def outcome(classification, reason, geometry=None):
        return geometry, {"classification": classification, "reason_code": reason,
                          "validation_policy": POLICY}
    if envelope.capture_completeness is not CaptureCompleteness.COMPLETE:
        return outcome("INCOMPLETE", "incomplete-capture")
    if (parsed.parser_name, parsed.parser_version, parsed.result_kind) != (
            "auto-g16-v3-gaussian-job", "1.2.0", "gaussian-job-facts"):
        return outcome("UNSUPPORTED", "unsupported-result-tuple")
    if parsed.parse_status is ParseStatus.UNSUPPORTED:
        return outcome("UNSUPPORTED", "unsupported-parse-status")
    if parsed.parse_status is not ParseStatus.PARSED or not parsed.facts:
        return outcome("INCOMPLETE", "incomplete-parse")
    facts = parsed.facts
    if facts["normal_termination_count"] != 1 or facts["error_termination_count"] != 0:
        return outcome("INCOMPLETE", "incomplete-normal-termination")
    _require(not facts["optimization_completed_marker"] and not facts["stationary_point_marker"]
             and not facts["optimization_completed_evidence"] and not facts["stationary_point_evidence"],
             "Freq result contains optimization evidence")
    expected = expected_geometry["atoms"]
    if len(expected) != 14 or [a["atomic_number"] for a in expected] != [6]*4+[1]*10:
        return outcome("UNSUPPORTED", "unsupported-atom-domain")
    _require([a["center"] for a in expected] == list(range(1, 15))
             and expected_geometry["units"] == "angstrom", "Opt geometry mapping differs")
    # The supported domain is nonlinear. Exact atom mapping is not an RMSD fit.
    points = [tuple(a[k] for k in ("x", "y", "z")) for a in expected]
    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    vectors = [tuple(x-y for x,y in zip(p, points[0])) for p in points[1:]]
    if not any(sum(x*x for x in cross(a,b)) > 1e-16 for a in vectors for b in vectors):
        return outcome("UNSUPPORTED", "unsupported-linear-domain")
    source, section = facts["source_artifact"], facts["job_section"]
    _require(len(envelope.artifacts) == 1, "Freq envelope artifact inventory differs")
    artifact = envelope.artifacts[0]
    _require(all(source[k] == v for k,v in {
        "sha256":artifact.sha256, "size_bytes":artifact.size_bytes,
        "logical_name":artifact.logical_name, "artifact_kind":artifact.artifact_kind,
        "envelope_observation_id":envelope.observation_id}.items()), "Freq envelope/source differs")
    def span(value):
        _require(isinstance(value, Mapping) and set(value) == set(source) | {"start", "end"}
                 and all(value[k] == v for k,v in source.items())
                 and type(value["start"]) is int and type(value["end"]) is int
                 and 0 <= section["start"] <= value["start"] < value["end"] <= section["end"] <= artifact.size_bytes,
                 "Freq span is not attributed to its unique job")
        return value["start"], value["end"]
    span(section)
    geometries, blocks = facts["geometry_blocks"], facts["frequency_blocks"]
    all_spans = sorted(span(b["source_span"]) for b in (*geometries, *blocks))
    _require(all(a[1] <= b[0] for a,b in zip(all_spans,all_spans[1:])), "Freq spans overlap or duplicate")
    values = tuple(v for block in blocks for v in block["frequencies_cm-1"])
    _require(all(type(v) in (float,int) and isfinite(v) for v in values)
             and values == tuple(facts["frequencies_cm-1"])
             and facts["frequency_count"] == len(values)
             and facts["imaginary_frequency_count"] == sum(v < 0.0 for v in values),
             "Freq facts are inconsistent")
    _require(list(blocks) == sorted(blocks, key=lambda b:b["source_span"]["start"]), "Freq blocks are unordered")
    inputs = [b for b in geometries if b["orientation_kind"] == "input-orientation"]
    for geometry in inputs:
        _require(geometry["units"] == "angstrom" and geometry["atoms"] == expected,
                 "Freq Input orientation conflicts with exact Opt/input geometry")
    if not blocks:
        return outcome("INCOMPLETE", "incomplete-mode-count")
    before = [g for g in inputs if g["source_span"]["end"] <= blocks[0]["source_span"]["start"]]
    if not before:
        return outcome("INCOMPLETE", "missing-frequency-geometry")
    selected = max(before, key=lambda b:b["source_span"]["start"])
    # Duplicate/tied starts were rejected by the source-span overlap check.
    if len(values) > 36:
        return outcome("UNSUPPORTED", "unsupported-mode-count", selected)
    if len(values) < 36:
        return outcome("INCOMPLETE", "incomplete-mode-count", selected)
    if any(v < 0.0 for v in values):
        return outcome("NOT_MINIMUM", "negative-frequency", selected)
    return outcome("VALIDATED_TWO_STAGE_MINIMUM", "complete-two-stage-minimum", selected)
