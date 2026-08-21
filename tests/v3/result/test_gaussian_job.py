from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from auto_g16.core import RecordConflictError, Result
from auto_g16.result import (
    CaptureCompleteness,
    CaptureStatus,
    GaussianJobParser,
    GaussianLogParser,
    MalformedEnvelopeError,
    OutputArtifact,
    OutputEnvelope,
    PARSED_RESULT_TYPE,
    ParseOutcome,
    ParseStatus,
    ProvenanceConflictError,
    ResultBoundaryError,
    ResultProvenanceService,
)
from auto_g16.result.gaussian_job import _recognize, _tokenize
from tests.v3.result.test_service import binding, initialized_store


LINES = (
    b" Entering Gaussian System, Link 0=g16",
    b" Optimization completed.",
    b" Frequencies -- -999.0",
    b" --Link1--",
    b" Normal termination of Gaussian 16",
    b" Symbolic Z-matrix:",
    b" Charge = 0 Multiplicity = 1",
    b" H 0.0 0.0 0.0",
    b" GradGradGrad",
    b" SCF Done: E(RHF) = -75.000000 A.U. after 10 cycles",
    b" Item Value Threshold Converged?",
    b" Maximum Force 0.000001 0.000450 YES",
    b" RMS Force 0.000001 0.000300 YES",
    b" Maximum Displacement 0.000001 0.001800 YES",
    b" RMS Displacement 0.000001 0.001200 YES",
    b" Optimization completed.",
    b" -- Stationary point found.",
    b" Harmonic frequencies (cm**-1), IR intensities (KM/Mole), Raman scattering",
    b" activities (A**4/AMU), depolarization ratios for plane and unpolarized",
    b" incident light, reduced masses (AMU), force constants (mDyne/A),",
    b" and normal coordinates:",
    b" 1 2 3",
    b" A1 A1 A1",
    b" Frequencies -- -123.4 200.0 300.0",
    b" Red. masses -- 1.0 2.0 3.0",
    b" Frc consts -- 0.1 0.2 0.3",
    b" IR Inten -- 10.0 20.0 30.0",
    b" Standard orientation:",
    b" -----",
    b" Center Atomic Atomic Coordinates (Angstroms)",
    b" Number Number Type X Y Z",
    b" -----",
    b" 1 8 0 0.0 0.0 0.0",
    b" 2 1 0 0.0 0.0 1.0",
    b" -----",
    b" Thermal correction to Gibbs Free Energy= 0.010000",
    b" Normal termination of Gaussian 16",
)


def transcript(
    *,
    eol: bytes = b"\n",
    final_eol: bool = True,
    replacements: dict[int, bytes] | None = None,
    insertions: dict[int, tuple[bytes, ...]] | None = None,
    stop: int | None = None,
) -> bytes:
    rows: list[bytes] = []
    changes = {} if replacements is None else replacements
    additions = {} if insertions is None else insertions
    for index, original in enumerate(LINES[:stop]):
        rows.extend(additions.get(index, ()))
        rows.append(changes.get(index, original))
    data = eol.join(rows)
    return data + eol if final_eol else data


def envelope(
    data: bytes,
    *,
    completeness: CaptureCompleteness = CaptureCompleteness.COMPLETE,
    artifacts: tuple[tuple[str, str, bytes], ...] | None = None,
    source: str = "capture-1",
) -> tuple[OutputEnvelope, dict[str, bytes]]:
    specs = (("gaussian-log", "job.log", data),) if artifacts is None else artifacts
    records = tuple(
        OutputArtifact(
            artifact_kind=kind,
            logical_name=name,
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )
        for kind, name, raw in specs
    )
    item = binding()
    result = OutputEnvelope(
        attempt_id=item.attempt_id,
        input_binding_observation_id=item.observation_id,
        execution_snapshot_id=item.execution_snapshot_id,
        capture_source_id=source,
        capture_sequence=1,
        capture_status=CaptureStatus.CAPTURED,
        capture_completeness=completeness,
        artifacts=records,
        capture_manifest_sha256="a" * 64,
        captured_at_utc="2026-08-21T00:00:00Z",
    )
    return result, {name: raw for _, name, raw in specs}


def parse(data: bytes, **kwargs: object) -> ParseOutcome:
    item, supplied = envelope(data, **kwargs)
    return GaussianJobParser().parse(item, supplied)


def source_for(data: bytes) -> dict[str, object]:
    item, _ = envelope(data)
    artifact = item.artifacts[0]
    return {
        "envelope_observation_id": item.observation_id,
        "artifact_kind": "gaussian-log",
        "logical_name": "job.log",
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def thaw(value: object) -> object:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


class GaussianJobParserTests(unittest.TestCase):
    def test_public_tuple_clean_lf_and_echo_suppression(self) -> None:
        outcome = parse(transcript())
        self.assertEqual(
            (
                GaussianJobParser.parser_name,
                GaussianJobParser.parser_version,
                GaussianJobParser.result_kind,
            ),
            ("auto-g16-v3-gaussian-job", "1.0.0", "gaussian-job-facts"),
        )
        self.assertEqual(outcome.parse_status, ParseStatus.PARSED)
        self.assertEqual(outcome.diagnostics, ())
        facts = outcome.facts
        self.assertEqual(facts["job_section"]["start"], 0)
        self.assertEqual(facts["job_section"]["end"], 1115)
        self.assertEqual(facts["scf_calculations"][0]["source_span"]["start"], 210)
        self.assertEqual(facts["scf_calculations"][0]["source_span"]["end"], 262)
        self.assertEqual(facts["optimization_completed_evidence"][0]["start"], 449)
        self.assertEqual(facts["optimization_completed_evidence"][0]["end"], 474)
        self.assertEqual(facts["stationary_point_evidence"][0]["start"], 474)
        self.assertEqual(facts["stationary_point_evidence"][0]["end"], 502)
        self.assertEqual(facts["frequency_blocks"][0]["source_span"]["start"], 740)
        self.assertEqual(facts["frequency_blocks"][0]["source_span"]["end"], 875)
        self.assertEqual(facts["geometry_blocks"][0]["source_span"]["start"], 875)
        self.assertEqual(facts["geometry_blocks"][0]["source_span"]["end"], 1029)
        self.assertEqual(
            facts["thermochemistry"]["thermal_correction_gibbs_hartree"]["source_span"]["start"],
            1029,
        )
        self.assertEqual(facts["termination_evidence"][0]["source_span"]["start"], 1080)
        self.assertEqual(facts["frequencies_cm-1"], (-123.4, 200.0, 300.0))
        self.assertEqual(facts["imaginary_frequency_count"], 1)
        self.assertEqual(len(facts["geometry_blocks"]), 1)
        self.assertNotIn("scientific_acceptance", facts)
        self.assertNotIn(-999.0, facts["frequencies_cm-1"])

    def test_crlf_and_unterminated_terminal_keep_original_byte_offsets(self) -> None:
        lf_lines, failed = _tokenize(transcript())
        self.assertIsNone(failed)
        self.assertEqual(
            (lf_lines[0].start, lf_lines[0].content_end, lf_lines[0].end),
            (0, 37, 38),
        )
        self.assertEqual(
            (lf_lines[-1].start, lf_lines[-1].content_end, lf_lines[-1].end),
            (1080, 1114, 1115),
        )
        crlf = parse(transcript(eol=b"\r\n"))
        self.assertEqual(crlf.parse_status, ParseStatus.PARSED)
        self.assertEqual(crlf.facts["job_section"]["end"], 1152)
        self.assertEqual(crlf.facts["scf_calculations"][0]["source_span"]["start"], 219)
        self.assertEqual(crlf.facts["scf_calculations"][0]["source_span"]["end"], 272)
        self.assertEqual(crlf.facts["frequency_blocks"][0]["source_span"]["start"], 761)
        self.assertEqual(crlf.facts["frequency_blocks"][0]["source_span"]["end"], 902)
        self.assertEqual(crlf.facts["geometry_blocks"][0]["source_span"]["start"], 902)
        self.assertEqual(crlf.facts["geometry_blocks"][0]["source_span"]["end"], 1064)
        self.assertEqual(crlf.facts["termination_evidence"][0]["source_span"]["start"], 1116)
        self.assertEqual(crlf.facts["termination_evidence"][0]["source_span"]["end"], 1152)
        crlf_lines, failed = _tokenize(transcript(eol=b"\r\n"))
        self.assertIsNone(failed)
        self.assertEqual(
            (crlf_lines[0].start, crlf_lines[0].content_end, crlf_lines[0].end),
            (0, 37, 39),
        )
        self.assertEqual(
            (
                crlf_lines[-1].start,
                crlf_lines[-1].content_end,
                crlf_lines[-1].end,
            ),
            (1116, 1150, 1152),
        )

        raw = transcript(final_eol=False)
        no_eol = parse(raw)
        self.assertEqual(no_eol.parse_status, ParseStatus.PARSED)
        self.assertEqual(no_eol.facts["job_section"]["end"], 1114)
        self.assertEqual(no_eol.facts["termination_evidence"][0]["source_span"]["end"], len(raw))
        no_eol_lines, failed = _tokenize(raw)
        self.assertIsNone(failed)
        self.assertEqual(
            (
                no_eol_lines[-1].start,
                no_eol_lines[-1].content_end,
                no_eol_lines[-1].end,
            ),
            (1080, 1114, 1114),
        )

    def test_artifact_matrix_precedes_grammar_and_mismatch_raises(self) -> None:
        bad = b"\rnot grammar"
        for completeness, specs, expected_status, expected_code in (
            (CaptureCompleteness.PARTIAL, (("stdout", "stdout.txt", bad),), ParseStatus.PARTIAL, "capture-partial"),
            (CaptureCompleteness.PARTIAL, (("gaussian-log", "a.log", bad),), ParseStatus.PARTIAL, "capture-partial"),
            (CaptureCompleteness.PARTIAL, (("gaussian-log", "a.log", bad), ("gaussian-log", "b.log", bad)), ParseStatus.PARTIAL, "capture-partial"),
            (CaptureCompleteness.COMPLETE, (("stdout", "stdout.txt", bad),), ParseStatus.UNSUPPORTED, "unsupported-gaussian-log-cardinality"),
            (CaptureCompleteness.COMPLETE, (("gaussian-log", "a.log", bad), ("gaussian-log", "b.log", bad)), ParseStatus.UNSUPPORTED, "unsupported-gaussian-log-cardinality"),
        ):
            with self.subTest(completeness=completeness, count=len(specs)):
                item, supplied = envelope(bad, completeness=completeness, artifacts=specs)
                result = GaussianJobParser().parse(item, supplied)
                self.assertEqual(result.parse_status, expected_status)
                self.assertEqual(result.facts, {})
                self.assertEqual(result.diagnostics, (expected_code,))
        item, supplied = envelope(transcript())
        for altered in ({}, {"job.log": b"wrong"}, {**supplied, "extra": b""}):
            with self.subTest(altered=altered), self.assertRaises(MalformedEnvelopeError):
                GaussianJobParser().parse(item, altered)
        with self.assertRaises(MalformedEnvelopeError):
            GaussianJobParser().parse(item, {"job.log": "not-bytes"})  # type: ignore[dict-item]

    def test_link1_and_terminal_boundaries(self) -> None:
        genuine = parse(transcript(insertions={35: (b" --Link1--",)}))
        self.assertEqual((genuine.parse_status, genuine.diagnostics), (ParseStatus.UNSUPPORTED, ("unsupported-multiple-job",)))
        internal = parse(transcript(insertions={35: (b" Proceeding to internal job step number 2.",)}))
        self.assertEqual(internal.diagnostics, ("unsupported-multiple-job",))
        second = parse(transcript(insertions={35: (b" Entering Gaussian System, Link 0=g16",)}))
        self.assertEqual(second.diagnostics, ("unsupported-multiple-job",))
        trailing = parse(transcript() + b"not blank\n")
        self.assertEqual(trailing.diagnostics, ("unparseable-trailing-content",))
        trailing_blanks = parse(transcript() + b" \t\n\n")
        self.assertEqual(trailing_blanks.parse_status, ParseStatus.PARSED)
        self.assertEqual(trailing_blanks.facts["job_section"]["end"], 1115)
        missing = parse(transcript(stop=36))
        self.assertEqual(missing.diagnostics, ("unparseable-terminal",))
        truncated = parse(transcript(replacements={36: b" Normal termination of Gaussian"}))
        self.assertEqual(truncated.diagnostics, ("unparseable-terminal",))
        lone_cr = parse(transcript().replace(b"SCF Done", b"SCF\rDone", 1))
        self.assertEqual(lone_cr.diagnostics, ("unparseable-line-terminator",))

    def test_fake_job_markers_in_echo_and_exact_anchor_in_child(self) -> None:
        echoed = parse(
            transcript(
                insertions={
                    5: (
                        b" Entering Gaussian System, Link 0=g16",
                        b" Entering Link 1",
                        b" --Link1--",
                    )
                }
            )
        )
        self.assertEqual(echoed.parse_status, ParseStatus.PARSED)
        child = transcript(replacements={12: b" --Link1--"})
        recognized = _recognize(child, source_for(child))
        self.assertEqual(recognized.diagnostic, "unparseable-orphan-anchor")
        self.assertEqual(recognized.failure_span, (332, 343))
        blank_symmetry = parse(transcript(replacements={22: b""}))
        self.assertEqual(blank_symmetry.diagnostics, ("unparseable-frequency-block",))

    def test_capability_boundaries_error_terminal_and_echo_boundary(self) -> None:
        error = parse(
            transcript(
                replacements={
                    36: b" Error termination via Lnk1e in /opt/g16/l9999.exe at Thu Aug 21 00:00:00 2026."
                }
            )
        )
        self.assertEqual(error.parse_status, ParseStatus.PARSED)
        self.assertEqual(error.facts["program_status"], "error-termination")
        self.assertEqual(error.facts["error_termination_count"], 1)
        self.assertEqual(error.facts["normal_termination_count"], 0)
        unsupported_program = parse(
            b" Entering Gaussian System, Link 0=g09\n"
        )
        self.assertEqual(
            (unsupported_program.parse_status, unsupported_program.diagnostics),
            (ParseStatus.UNSUPPORTED, ("unsupported-program",)),
        )
        unsupported_orientation = parse(
            transcript(insertions={9: (b" Z-Matrix orientation:",)})
        )
        self.assertEqual(
            unsupported_orientation.diagnostics,
            ("unsupported-valid-gaussian-grammar",),
        )
        duplicate_charge = parse(
            transcript(insertions={7: (b" Charge = 0 Multiplicity = 1",)})
        )
        self.assertEqual(duplicate_charge.diagnostics, ("unparseable-echo-boundary",))
        no_job = parse(b"ordinary preamble\n")
        self.assertEqual(no_job.diagnostics, ("unparseable-job-start",))

    def test_machine_prefix_dispatch_is_closed_and_single_owner(self) -> None:
        cases = (
            (b" SCF Done: malformed", "unparseable-malformed-prefix"),
            (b" SCF Done: E(RHF) = NaN A.U.", "unparseable-numeric-token"),
            (b" Item Value Threshold", "unparseable-malformed-prefix"),
            (b" Harmonic frequencies malformed", "unparseable-malformed-prefix"),
            (b" Standard orientation: extra", "unparseable-malformed-prefix"),
            (b" Normal termination malformed", "unparseable-terminal"),
        )
        for line, expected in cases:
            with self.subTest(line=line):
                result = parse(transcript(insertions={9: (line,)}))
                self.assertEqual(result.facts, {})
                self.assertEqual(result.diagnostics, (expected,))

    def test_frequency_failure_ownership_and_fail_fast(self) -> None:
        numeric = transcript(replacements={23: b" Frequencies -- NaN 200.0 300.0"})
        result = parse(numeric)
        self.assertEqual(result.diagnostics, ("unparseable-numeric-token",))
        private = _recognize(numeric, source_for(numeric))
        self.assertEqual(private.failure_span, (773, 776))
        wrong_count = parse(transcript(replacements={23: b" Frequencies -- 100.0 200.0"}))
        self.assertEqual(wrong_count.diagnostics, ("unparseable-frequency-block",))
        truncated = parse(transcript(replacements={24: b"not red masses"}))
        self.assertEqual(truncated.diagnostics, ("unparseable-frequency-block",))
        orphan = parse(transcript(insertions={9: (b" Frequencies -- 1.0",)}))
        self.assertEqual(orphan.diagnostics, ("unparseable-orphan-anchor",))
        malformed_child_anchor = parse(
            transcript(replacements={18: b" activities (A**4/AMU)"})
        )
        self.assertEqual(
            malformed_child_anchor.diagnostics,
            ("unparseable-frequency-block",),
        )

    def test_optimization_failure_ownership(self) -> None:
        numeric = parse(transcript(replacements={11: b" Maximum Force NaN 0.000450 YES"}))
        self.assertEqual(numeric.diagnostics, ("unparseable-numeric-token",))
        structural = parse(transcript(replacements={12: b" RMS Force 0.0 YES"}))
        self.assertEqual(structural.diagnostics, ("unparseable-optimization-block",))
        malformed_stationary = parse(transcript(replacements={16: b" -- Stationary point found"}))
        self.assertEqual(malformed_stationary.diagnostics, ("unparseable-optimization-block",))
        orphan = parse(transcript(insertions={9: (b" -- Stationary point found.",)}))
        self.assertEqual(orphan.diagnostics, ("unparseable-orphan-anchor",))
        malformed_prefix = parse(transcript(insertions={9: (b" -- Stationary point found",)}))
        self.assertEqual(malformed_prefix.diagnostics, ("unparseable-malformed-prefix",))
        for exact_child_anchor in (
            b" Maximum Force 0.000001 0.000450 YES",
            b" RMS Force 0.000001 0.000300 YES",
            b" Maximum Displacement 0.000001 0.001800 YES",
            b" RMS Displacement 0.000001 0.001200 YES",
            b" Predicted change in Energy=-1.0D-06",
        ):
            with self.subTest(anchor=exact_child_anchor):
                result = parse(
                    transcript(insertions={9: (exact_child_anchor,)})
                )
                self.assertEqual(
                    result.diagnostics,
                    ("unparseable-orphan-anchor",),
                )
        thermo_in_child = parse(
            transcript(
                insertions={
                    12: (b" Thermal correction to Gibbs Free Energy= 0.010000",)
                }
            )
        )
        self.assertEqual(
            thermo_in_child.diagnostics,
            ("unparseable-orphan-anchor",),
        )

    def test_geometry_failure_ownership_and_all_blocks(self) -> None:
        malformed_header = parse(transcript(replacements={29: b" wrong header"}))
        self.assertEqual(malformed_header.diagnostics, ("unparseable-geometry-block",))
        wrong_fields = parse(transcript(replacements={32: b" 1 8 0 0.0 0.0"}))
        self.assertEqual(wrong_fields.diagnostics, ("unparseable-geometry-row",))
        numeric = parse(transcript(replacements={32: b" 1 8 0 NaN 0.0 0.0"}))
        self.assertEqual(numeric.diagnostics, ("unparseable-numeric-token",))
        noncontiguous = parse(transcript(replacements={33: b" 3 1 0 0.0 0.0 1.0"}))
        self.assertEqual(noncontiguous.diagnostics, ("unparseable-geometry-row",))
        out_of_range = parse(transcript(replacements={32: b" 1 119 0 0.0 0.0 0.0"}))
        self.assertEqual(out_of_range.diagnostics, ("unparseable-geometry-row",))
        no_close = parse(transcript(replacements={34: b" ----"}))
        self.assertEqual(no_close.diagnostics, ("unparseable-geometry-block",))
        dummy = parse(transcript(replacements={32: b" 1 0 0 0.0 0.0 0.0"}))
        self.assertEqual(dummy.facts["geometry_blocks"][0]["atoms"][0]["atomic_number"], 0)
        two = parse(transcript(insertions={35: tuple(LINES[27:35])}))
        self.assertEqual(len(two.facts["geometry_blocks"]), 2)
        raw = transcript(replacements={32: b" 1 8 0 NaN Inf 0.0"})
        leftmost = _recognize(raw, source_for(raw))
        self.assertEqual(leftmost.diagnostic, "unparseable-numeric-token")
        self.assertEqual(leftmost.failure_span, (991, 994))
        earlier = parse(
            transcript(
                replacements={32: b" 1 8 0 0.0 0.0"},
                insertions={35: (b" Frequencies -- NaN",)},
            )
        )
        self.assertEqual(earlier.diagnostics, ("unparseable-geometry-row",))

    def test_thermochemistry_precedence_and_duplicate_spans(self) -> None:
        duplicate = b" Thermal correction to Gibbs Free Energy= 0.010000"
        for eol, expected in ((b"\n", (1080, 1131)), (b"\r\n", (1116, 1168))):
            raw = transcript(eol=eol, insertions={36: (duplicate,)})
            result = parse(raw)
            self.assertEqual(result.diagnostics, ("unparseable-duplicate-evidence",))
            self.assertEqual(_recognize(raw, source_for(raw)).failure_span, expected)
        raw = transcript(stop=36, final_eol=True) + duplicate
        self.assertEqual(parse(raw).diagnostics, ("unparseable-duplicate-evidence",))
        self.assertEqual(_recognize(raw, source_for(raw)).failure_span, (1080, len(raw)))
        for bad in (b"NaN", b"Inf"):
            line = b" Thermal correction to Gibbs Free Energy= " + bad
            result = parse(transcript(insertions={36: (line,)}))
            self.assertEqual(result.diagnostics, ("unparseable-numeric-token",))
        malformed = parse(transcript(insertions={36: (b" Thermal correction to Gibbs Free Energy= 0.1 extra",)}))
        self.assertEqual(malformed.diagnostics, ("unparseable-malformed-prefix",))
        different = parse(transcript(insertions={36: (b" Thermal correction to Enthalpy= 0.020000",)}))
        self.assertEqual(different.parse_status, ParseStatus.PARSED)
        self.assertEqual(len(different.facts["thermochemistry"]), 2)
        first_bad = parse(
            transcript(
                replacements={35: b" Thermal correction to Gibbs Free Energy= NaN"},
                insertions={36: (duplicate,)},
            )
        )
        self.assertEqual(first_bad.diagnostics, ("unparseable-numeric-token",))

    def test_eof_diagnostic_uses_last_consumed_grammar_line(self) -> None:
        cases = (
            (b"ordinary preamble\n", "unparseable-job-start", 18, None),
            (transcript(stop=5), "unparseable-echo-boundary", 132, (0, 38)),
            (transcript(stop=12), "unparseable-optimization-block", 332, (295, 332)),
            (transcript(stop=23), "unparseable-frequency-block", 757, (747, 757)),
            (transcript(stop=34), "unparseable-geometry-block", 1022, (1003, 1022)),
            (
                transcript(stop=10) + b"unrelated machine text\n",
                "unparseable-terminal",
                285,
                (210, 262),
            ),
            (
                transcript(stop=27) + b"displacement text\n",
                "unparseable-terminal",
                893,
                (847, 875),
            ),
        )
        for raw, code, position, span in cases:
            with self.subTest(code=code, size=len(raw)):
                failure = _recognize(raw, source_for(raw))
                self.assertEqual(failure.diagnostic, code)
                self.assertEqual(failure.failure_position, position)
                self.assertEqual(failure.failure_span, span)

    def test_replay_v1_coexistence_persistence_and_span_forgery(self) -> None:
        data = transcript()
        item, supplied = envelope(data)
        new = GaussianJobParser().parse(item, supplied)
        replay = GaussianJobParser().parse(item, supplied)
        old = GaussianLogParser().parse(item, supplied)
        self.assertEqual(new, replay)
        self.assertEqual(new.result_id, replay.result_id)
        self.assertNotEqual(new.result_id, old.result_id)
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "runtime.sqlite3"
            store = initialized_store(database)
            service = ResultProvenanceService(store)
            service.record_input_binding(binding())
            service.record_output_envelope(item)
            service.record_parse_outcome(old)
            service.record_parse_outcome(new)
            store.close()
            with initialized_store(database) as reopened:
                view = ResultProvenanceService(reopened).current_view("attempt-1")
                self.assertEqual({result.result_kind for result in view.selected_results}, {"gaussian-log-facts", "gaussian-job-facts"})

        payload = thaw(new.payload())
        payload["facts"]["source_artifact"]["envelope_observation_id"] = "other-envelope"
        for key in ("job_section",):
            payload["facts"][key]["envelope_observation_id"] = "other-envelope"
        for collection in ("termination_evidence", "optimization_completed_evidence", "stationary_point_evidence", "scf_calculations", "frequency_blocks", "geometry_blocks"):
            for evidence in payload["facts"][collection]:
                target = evidence if collection in {"optimization_completed_evidence", "stationary_point_evidence"} else evidence["source_span"]
                target["envelope_observation_id"] = "other-envelope"
        for evidence in payload["facts"]["thermochemistry"].values():
            evidence["source_span"]["envelope_observation_id"] = "other-envelope"
        forged = ParseOutcome.from_payload(payload)
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            service.record_input_binding(binding())
            service.record_output_envelope(item)
            with self.assertRaisesRegex(ProvenanceConflictError, "another output envelope"):
                service.record_parse_outcome(forged)

    def test_span_schema_overlap_capture_identity_and_payload_conflict(self) -> None:
        data = transcript()
        item, supplied = envelope(data)
        parsed = GaussianJobParser().parse(item, supplied)

        out_of_range = thaw(parsed.payload())
        out_of_range["facts"]["job_section"]["end"] = len(data) + 1
        with self.assertRaisesRegex(ResultBoundaryError, "half-open"):
            ParseOutcome.from_payload(out_of_range)

        overlapping = thaw(parsed.payload())
        overlapping["facts"]["frequency_blocks"][0]["source_span"]["start"] = 210
        overlapping["facts"]["frequency_blocks"][0]["source_span"]["end"] = 262
        with self.assertRaisesRegex(ResultBoundaryError, "overlap"):
            ParseOutcome.from_payload(overlapping)

        changed_span_payload = thaw(parsed.payload())
        changed_span_payload["facts"]["scf_calculations"][0]["source_span"]["start"] = 211
        changed_span = ParseOutcome.from_payload(changed_span_payload)
        self.assertEqual(changed_span.result_id, parsed.result_id)
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            service.record_input_binding(binding())
            service.record_output_envelope(item)
            service.record_parse_outcome(parsed)
            with self.assertRaises(RecordConflictError):
                service.record_parse_outcome(changed_span)

        changed_envelope, changed_supplied = envelope(
            data, source="capture-2"
        )
        changed_capture = GaussianJobParser().parse(
            changed_envelope, changed_supplied
        )
        self.assertNotEqual(parsed.envelope_observation_id, changed_capture.envelope_observation_id)
        self.assertNotEqual(parsed.result_id, changed_capture.result_id)

    def test_closed_schema_and_unknown_new_tuple_fail(self) -> None:
        parsed = parse(transcript())
        payload = thaw(parsed.payload())
        payload["facts"]["scientific_acceptance"] = True
        with self.assertRaises(ResultBoundaryError):
            ParseOutcome.from_payload(payload)
        payload = thaw(parsed.payload())
        payload["parser_version"] = "2.0.0"
        with self.assertRaisesRegex(ResultBoundaryError, "unsupported parser tuple"):
            ParseOutcome.from_payload(payload)
        payload = thaw(parsed.payload())
        payload["facts"]["facts_schema_version"] = True
        with self.assertRaisesRegex(ResultBoundaryError, "facts_schema_version"):
            ParseOutcome.from_payload(payload)
        payload = thaw(parsed.payload())
        payload["facts"]["geometry_blocks"][0]["atoms"][0]["center"] = True
        with self.assertRaisesRegex(ResultBoundaryError, "geometry center"):
            ParseOutcome.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
