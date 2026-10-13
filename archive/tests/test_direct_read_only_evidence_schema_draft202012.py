#!/usr/bin/env python3
"""Pinned Draft 2020-12 parity for direct read-only evidence schemas."""

from __future__ import annotations

import copy
import importlib.metadata
import json
import os
import re
import sys
import unittest
from pathlib import Path


REQUIRE_ENV = "AUTO_G16_REQUIRE_JSONSCHEMA"
EXPECTED_JSONSCHEMA_VERSION = "4.26.0"
raw_requirement = os.environ.get(REQUIRE_ENV, "")
if raw_requirement not in {"", "0", "1"}:
    raise RuntimeError(f"{REQUIRE_ENV} must be unset, 0, or 1")
REQUIRE_JSONSCHEMA = raw_requirement == "1"

try:
    import jsonschema
except ImportError as exc:
    jsonschema = None
    JSONSCHEMA_IMPORT_ERROR: Exception | None = exc
else:
    JSONSCHEMA_IMPORT_ERROR = None

installed_jsonschema = (
    importlib.metadata.version("jsonschema") if jsonschema is not None else None
)
EXACT_VALIDATOR_AVAILABLE = (
    jsonschema is not None and installed_jsonschema == EXPECTED_JSONSCHEMA_VERSION
)
if REQUIRE_JSONSCHEMA and not EXACT_VALIDATOR_AVAILABLE:
    detail = (
        f"installed jsonschema={installed_jsonschema!r}"
        if JSONSCHEMA_IMPORT_ERROR is None
        else f"import failed: {JSONSCHEMA_IMPORT_ERROR}"
    )
    raise RuntimeError(
        f"{REQUIRE_ENV}=1 requires jsonschema=={EXPECTED_JSONSCHEMA_VERSION}; {detail}"
    )


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import direct_read_only_evidence as EVIDENCE  # noqa: E402


SCHEMA_PATHS = {
    "evidence": ROOT / "contracts/direct-execution/direct-qstat-evidence-core.schema.json",
    "receipt": ROOT / "contracts/direct-execution/direct-scheduler-terminal-evidence-receipt.schema.json",
}


@unittest.skipUnless(
    EXACT_VALIDATOR_AVAILABLE,
    "real Draft 2020-12 checks require jsonschema==4.26.0",
)
class DirectReadOnlyEvidenceSchemaDraft202012Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert jsonschema is not None
        cls.schemas = {
            name: json.loads(path.read_text(encoding="utf-8"))
            for name, path in SCHEMA_PATHS.items()
        }
        cls.validators = {
            name: jsonschema.Draft202012Validator(
                schema,
                format_checker=jsonschema.FormatChecker(),
            )
            for name, schema in cls.schemas.items()
        }

    def setUp(self) -> None:
        binding = EVIDENCE.DirectJobBinding(
            project="schemajob",
            job_id="123.master",
            attempt_id="qsub-attempt-" + "a" * 64,
            input_sha256="b" * 64,
            direct_binding_sha256="c" * 64,
        )
        self.binding = binding
        observation = EVIDENCE.QstatObservation(
            returncode=0,
            stdout=(
                b"Job Id: 123.master\n"
                b"    Job_Name = schemajob\n"
                b"    job_state = C\n"
                b"    exit_status = 0\n"
            ),
            stderr=b"",
            timed_out=False,
            eof_complete=True,
            requested_at="2026-08-06T00:00:00.000000Z",
            collected_at="2026-08-06T00:00:01.000000Z",
            received_at="2026-08-06T00:00:02.000000Z",
        )
        self.evidence_wrapper = EVIDENCE.build_qstat_evidence(binding, observation)
        self.unknown_document = EVIDENCE.build_qstat_evidence(
            binding,
            EVIDENCE.QstatObservation(
                returncode=1,
                stdout=b"",
                stderr=b"qstat failed\n",
                timed_out=False,
                eof_complete=True,
                requested_at="2026-08-06T00:00:00.000000Z",
                collected_at="2026-08-06T00:00:01.000000Z",
                received_at="2026-08-06T00:00:02.000000Z",
            ),
        ).document()
        self.absent_document = EVIDENCE.build_qstat_evidence(
            binding,
            EVIDENCE.QstatObservation(
                returncode=153,
                stdout=b"",
                stderr=b"qstat: Unknown Job Id 123.master\n",
                timed_out=False,
                eof_complete=True,
                requested_at="2026-08-06T00:00:00.000000Z",
                collected_at="2026-08-06T00:00:01.000000Z",
                received_at="2026-08-06T00:00:02.000000Z",
            ),
        ).document()
        self.documents = {
            "evidence": self.evidence_wrapper.document(),
            "receipt": EVIDENCE.build_terminal_receipt(self.evidence_wrapper).document(),
        }

    def owner_validate(self, name: str, document: dict[str, object]) -> dict:
        if name == "evidence":
            return EVIDENCE.validate_qstat_evidence(document)
        return EVIDENCE.validate_terminal_receipt(
            document,
            evidence=self.evidence_wrapper,
        )

    def assert_both_reject(self, name: str, changed: dict[str, object]) -> None:
        assert jsonschema is not None
        with self.assertRaises(jsonschema.ValidationError):
            self.validators[name].validate(changed)
        with self.assertRaises(EVIDENCE.DirectReadOnlyEvidenceError):
            self.owner_validate(name, changed)

    def rehash_evidence(self, document: dict[str, object]) -> dict[str, object]:
        changed = copy.deepcopy(document)
        qstat = changed["qstat"]
        observation_projection = copy.deepcopy(qstat)
        observation_projection.pop("observation_payload_sha256")
        qstat["observation_payload_sha256"] = EVIDENCE.digest(observation_projection)
        changed["qstat_evidence_sha256"] = ""
        changed["qstat_evidence_sha256"] = EVIDENCE.digest(changed)
        return changed

    def test_real_draft_accepts_owner_documents(self) -> None:
        for name, document in self.documents.items():
            with self.subTest(name=name):
                self.validators[name].validate(document)
                self.assertEqual(self.owner_validate(name, document), document)

    def test_schemas_and_every_object_definition_are_closed(self) -> None:
        assert jsonschema is not None
        object_defs = {
            "evidence": (
                "topology",
                "binding",
                "collection",
                "present_qstat",
                "absent_qstat",
                "unknown_qstat",
                "authority",
            ),
            "receipt": ("topology", "binding", "authority"),
        }
        for name, schema in self.schemas.items():
            with self.subTest(name=name, location="top"):
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(set(schema["required"]), set(schema["properties"]))
                jsonschema.Draft202012Validator.check_schema(schema)
            for definition in object_defs[name]:
                value = schema["$defs"][definition]
                with self.subTest(name=name, definition=definition):
                    self.assertEqual(value["type"], "object")
                    self.assertFalse(value["additionalProperties"])
                    self.assertEqual(set(value["required"]), set(value["properties"]))

    def test_unknown_and_missing_top_level_fields_reject_both(self) -> None:
        for name, document in self.documents.items():
            changed = copy.deepcopy(document)
            changed["unexpected"] = False
            self.assert_both_reject(name, changed)
            changed = copy.deepcopy(document)
            del changed[next(iter(changed))]
            self.assert_both_reject(name, changed)

    def test_const_pattern_boolean_and_integer_mutations_reject_both(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        changed = copy.deepcopy(self.documents["evidence"])
        changed["topology"]["topology"] = "legacy_nested_ssh"
        cases.append(("evidence", changed))
        changed = copy.deepcopy(self.documents["evidence"])
        changed["binding"]["job_id"] = "123"
        cases.append(("evidence", changed))
        changed = copy.deepcopy(self.documents["evidence"])
        changed["binding"]["job_id"] = "123456789012345678901.master"
        cases.append(("evidence", changed))
        changed = copy.deepcopy(self.documents["evidence"])
        changed["collection"]["maximum_age_seconds"] = "121"
        cases.append(("evidence", changed))
        changed = copy.deepcopy(self.documents["evidence"])
        changed["qstat"]["pbs_state"] = "E"
        cases.append(("evidence", changed))
        changed = copy.deepcopy(self.documents["evidence"])
        changed["authority"]["authorizes_effect"] = True
        cases.append(("evidence", changed))
        changed = copy.deepcopy(self.unknown_document)
        changed["qstat"]["returncode"] = "-0"
        cases.append(("evidence", changed))
        changed = copy.deepcopy(self.documents["receipt"])
        changed["schema"] = "gaussian-terminal-inspection-receipt/2"
        cases.append(("receipt", changed))
        changed = copy.deepcopy(self.documents["receipt"])
        changed["pbs_state"] = "E"
        cases.append(("receipt", changed))
        changed = copy.deepcopy(self.documents["receipt"])
        changed["authority"]["scientific_acceptance"] = True
        cases.append(("receipt", changed))
        for name, changed in cases:
            with self.subTest(name=name, changed=changed):
                self.assert_both_reject(name, changed)

    def test_rehashed_present_and_absent_stream_size_splices_reject_both(self) -> None:
        for source, field, value in (
            (self.documents["evidence"], "stdout_size_bytes", "0"),
            (self.documents["evidence"], "stderr_size_bytes", "1"),
            (self.absent_document, "stdout_size_bytes", "1"),
            (self.absent_document, "stderr_size_bytes", "0"),
        ):
            with self.subTest(status=source["qstat"]["status"], field=field):
                changed = copy.deepcopy(source)
                changed["qstat"][field] = value
                self.assert_both_reject("evidence", self.rehash_evidence(changed))

    def test_oversize_timeout_and_eof_have_owner_schema_hash_parity(self) -> None:
        oversized = b"x" * (EVIDENCE.MAX_QSTAT_OUTPUT_BYTES + 1)
        for name, flags in (
            ("timeout", {"timed_out": True, "eof_complete": True}),
            ("incomplete-eof", {"timed_out": False, "eof_complete": False}),
        ):
            with self.subTest(case=name):
                document = EVIDENCE.build_qstat_evidence(
                    self.binding,
                    EVIDENCE.QstatObservation(
                        returncode=0,
                        stdout=oversized,
                        stderr=b"",
                        requested_at="2026-08-06T00:00:00.000000Z",
                        collected_at="2026-08-06T00:00:01.000000Z",
                        received_at="2026-08-06T00:00:02.000000Z",
                        **flags,
                    ),
                ).document()
                self.assertEqual(document["qstat"]["reason"], "output_too_large")
                qstat_projection = copy.deepcopy(document["qstat"])
                inner_hash = qstat_projection.pop("observation_payload_sha256")
                self.assertEqual(EVIDENCE.digest(qstat_projection), inner_hash)
                outer_projection = copy.deepcopy(document)
                outer_hash = outer_projection["qstat_evidence_sha256"]
                outer_projection["qstat_evidence_sha256"] = ""
                self.assertEqual(EVIDENCE.digest(outer_projection), outer_hash)
                self.validators["evidence"].validate(document)
                self.assertEqual(self.owner_validate("evidence", document), document)

    def test_all_portable_integer_positions_reject_float_and_bool_both(self) -> None:
        evidence_paths = (
            ("topology", "hop_count"),
            ("collection", "maximum_age_seconds"),
            ("collection", "age_seconds"),
            ("qstat", "returncode"),
            ("qstat", "stdout_size_bytes"),
            ("qstat", "stderr_size_bytes"),
        )
        cases: list[tuple[str, dict[str, object], tuple[str, str], object]] = []
        for path in evidence_paths:
            for hostile in (1.0, True):
                changed = copy.deepcopy(self.documents["evidence"])
                changed[path[0]][path[1]] = hostile
                cases.append(("evidence", changed, path, hostile))
        for hostile in (1.0, True):
            changed = copy.deepcopy(self.documents["receipt"])
            changed["topology"]["hop_count"] = hostile
            cases.append(("receipt", changed, ("topology", "hop_count"), hostile))
        self.assertEqual(len(cases), 14)
        for name, changed, path, hostile in cases:
            with self.subTest(name=name, path=path, hostile=hostile):
                self.assert_both_reject(name, changed)

    def test_job_id_schema_owner_and_w5_language_have_same_acceptance(self) -> None:
        evidence_pattern = self.schemas["evidence"]["$defs"]["job_id"]["pattern"]
        receipt_pattern = self.schemas["receipt"]["$defs"]["binding"]["properties"]["job_id"]["pattern"]
        self.assertEqual(evidence_pattern, EVIDENCE.JOB_ID_RE.pattern)
        self.assertEqual(receipt_pattern, EVIDENCE.JOB_ID_RE.pattern)
        w5_pattern = re.compile(
            r"^(?P<sequence>[1-9][0-9]{0,19})\.(?P<server>[A-Za-z0-9][A-Za-z0-9.-]{0,127})\n$"
        )
        for candidate in (
            "1.a",
            "123.master",
            "12345678901234567890.server.example",
            "123456789012345678901.master",
            "123",
            "0.master",
            "1.master;id",
        ):
            with self.subTest(candidate=candidate):
                self.assertEqual(
                    EVIDENCE.JOB_ID_RE.fullmatch(candidate) is not None,
                    w5_pattern.fullmatch(candidate + "\n") is not None,
                )
    def test_schema_acceptance_is_not_transport_or_terminal_science_authority(self) -> None:
        for name, document in self.documents.items():
            with self.subTest(name=name):
                self.validators[name].validate(document)
                self.assertIsInstance(copy.deepcopy(document), dict)
                self.assertFalse(document["authority"]["authorizes_effect"])
                self.assertFalse(document["authority"]["scientific_acceptance"])
                self.assertFalse(document["authority"]["production_supported"])
                self.assertFalse(document["authority"]["transport_implemented"])


if __name__ == "__main__":
    unittest.main()
