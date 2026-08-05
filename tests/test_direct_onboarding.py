#!/usr/bin/env python3
"""Focused hostile tests for v2.7 direct onboarding and support reporting."""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import io
import json
import socket
import subprocess
import sys
import unittest
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from tests.test_direct_root_owner_contract import DirectRootFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
DOC = ROOT / "docs/v2.7-direct-onboarding-support.md"
sys.path.insert(0, str(SCRIPTS))

import direct_onboarding as ONBOARDING  # noqa: E402
import direct_root_owner_contract as ROOT_OWNER  # noqa: E402
import direct_ssh_pbs_offline as DIRECT_OFFLINE  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


class DirectOnboardingTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.fixture = DirectRootFixture()
        self.profile = self.fixture.profile

    def run_cli(
        self,
        argv: list[str],
        document: dict[str, object] | bytes | None = None,
    ) -> tuple[int, str, str]:
        if type(document) is dict:
            raw = ROOT_OWNER.canonical_bytes(document)
        elif type(document) is bytes:
            raw = document
        else:
            raw = b""
        stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
        stdout_bytes = io.BytesIO()
        stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8")
        stderr_bytes = io.BytesIO()
        stderr = io.TextIOWrapper(stderr_bytes, encoding="utf-8")
        with (
            mock.patch.object(sys, "stdin", stdin),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(sys, "stderr", stderr),
        ):
            status = ONBOARDING.main(argv)
            stdout.flush()
            stderr.flush()
            return (
                status,
                stdout_bytes.getvalue().decode("utf-8"),
                stderr_bytes.getvalue().decode("utf-8"),
            )

    def assert_sanitized_support_snapshot_drift(self, **replacements: object) -> None:
        with ExitStack() as stack:
            for field, value in replacements.items():
                stack.enter_context(mock.patch.object(ONBOARDING, field, value))
            socket_call = stack.enter_context(mock.patch.object(socket, "socket"))
            subprocess_call = stack.enter_context(mock.patch.object(subprocess, "run"))
            network_call = stack.enter_context(
                mock.patch.object(urllib.request, "urlopen")
            )
            status, stdout, stderr = self.run_cli(["doctor"], self.profile)
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr,
            "ERROR pr6_support_snapshot_drift: "
            "the offline direct-backend support snapshot changed\n",
        )
        socket_call.assert_not_called()
        subprocess_call.assert_not_called()
        network_call.assert_not_called()

    def test_init_validate_doctor_are_offline_under_hostile_patches(self) -> None:
        with (
            mock.patch.object(socket, "socket") as socket_call,
            mock.patch.object(subprocess, "run") as subprocess_call,
            mock.patch.object(urllib.request, "urlopen") as network_call,
        ):
            init = self.run_cli(["init", "direct-profile-001"])
            validate = self.run_cli(["validate"], self.profile)
            doctor = self.run_cli(["doctor"], self.profile)

        for status, stdout, stderr in (init, validate, doctor):
            self.assertEqual(status, 0)
            self.assertTrue(stdout.endswith("\n"))
            self.assertEqual(stderr, "")
        socket_call.assert_not_called()
        subprocess_call.assert_not_called()
        network_call.assert_not_called()

    def test_oversized_stdin_is_bounded_sanitized_and_effect_free(self) -> None:
        oversized = b"{" + b"x" * ROOT_OWNER.MAX_DOCUMENT_BYTES
        with (
            mock.patch.object(socket, "socket") as socket_call,
            mock.patch.object(subprocess, "run") as subprocess_call,
            mock.patch.object(urllib.request, "urlopen") as network_call,
        ):
            status, stdout, stderr = self.run_cli(["doctor"], oversized)
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr,
            "ERROR invalid_input_size: direct onboarding input must be one bounded non-empty JSON document\n",
        )
        self.assertNotIn("x" * 64, stderr)
        socket_call.assert_not_called()
        subprocess_call.assert_not_called()
        network_call.assert_not_called()

    def test_integer_string_limit_is_sanitized_for_in_process_cli(self) -> None:
        hostile = b'{"value":' + (b"7" * 5000) + b"}"
        for command in ("validate", "doctor"):
            with self.subTest(command=command):
                status, stdout, stderr = self.run_cli([command], hostile)
                self.assertEqual(status, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    stderr,
                    "ERROR invalid_json: direct onboarding input is not one valid JSON document\n",
                )
                self.assertNotIn("7777777777777777", stderr)
                self.assertNotIn("Traceback", stderr)
                self.assertNotIn(str(ROOT), stderr)

    def test_integer_string_limit_is_sanitized_for_real_cli_process(self) -> None:
        hostile = b'{"value":' + (b"7" * 5000) + b"}"
        script = SCRIPTS / "direct_onboarding.py"
        for command in ("validate", "doctor"):
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, str(script), command],
                    cwd=ROOT,
                    input=hostile,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr,
                    b"ERROR invalid_json: direct onboarding input is not one valid JSON document\n",
                )
                self.assertNotIn(b"7777777777777777", result.stderr)
                self.assertNotIn(b"Traceback", result.stderr)
                self.assertNotIn(str(ROOT).encode("utf-8"), result.stderr)
                self.assertNotIn(str(script).encode("utf-8"), result.stderr)

    def test_malformed_inputs_never_escape_sanitized_cli_errors(self) -> None:
        cases = (
            (["init", "INVALID PROFILE"], None, "invalid_profile_id"),
            (["validate"], b'{"unterminated":', "invalid_json"),
            (["doctor"], b'{"nested":' + (b"[" * 2000), "invalid_json"),
        )
        for argv, document, error_code in cases:
            with self.subTest(argv=argv):
                status, stdout, stderr = self.run_cli(argv, document)
                self.assertEqual(status, 2)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith(f"ERROR {error_code}:"))
                self.assertNotIn("Traceback", stderr)
                self.assertNotIn(str(ROOT), stderr)

    def test_complete_pr6_authority_snapshot_fails_closed_on_any_drift(self) -> None:
        ONBOARDING._assert_pr6_non_authority()
        expected = ONBOARDING.EXPECTED_PR6_AUTHORITY
        candidates = []
        for field, value in expected.items():
            changed = copy.deepcopy(expected)
            changed[field] = not value
            candidates.append((f"changed-{field}", changed))
        for field in expected:
            changed = copy.deepcopy(expected)
            changed.pop(field)
            candidates.append((f"missing-{field}", changed))
        changed = copy.deepcopy(expected)
        changed["unexpected_authority"] = False
        candidates.append(("additional-field", changed))
        changed = copy.deepcopy(expected)
        changed["synthetic_only"] = 1
        candidates.append(("non-boolean-lookalike", changed))

        for label, candidate in candidates:
            with self.subTest(label=label):
                with mock.patch.object(DIRECT_OFFLINE, "AUTHORITY", candidate):
                    with self.assertRaisesRegex(
                        ONBOARDING.DirectOnboardingError,
                        "non-authority markers changed",
                    ) as raised:
                        ONBOARDING._assert_pr6_non_authority()
                self.assertEqual(raised.exception.code, "pr6_authority_drift")

        with mock.patch.object(DIRECT_OFFLINE, "AUTHORITY", None):
            with self.assertRaises(ONBOARDING.DirectOnboardingError) as raised:
                ONBOARDING._assert_pr6_non_authority()
        self.assertEqual(raised.exception.code, "pr6_authority_drift")

    def test_review_counterexamples_fail_closed_without_external_effect(self) -> None:
        cases = (
            ("init", "qdel_capability", True, ["init", "direct-profile-001"], None),
            ("validate", "automatic_retry", True, ["validate"], self.profile),
        )
        for label, field, value, argv, document in cases:
            authority = copy.deepcopy(ONBOARDING.EXPECTED_PR6_AUTHORITY)
            authority[field] = value
            with self.subTest(label=label):
                with (
                    mock.patch.object(DIRECT_OFFLINE, "AUTHORITY", authority),
                    mock.patch.object(socket, "socket") as socket_call,
                    mock.patch.object(subprocess, "run") as subprocess_call,
                    mock.patch.object(urllib.request, "urlopen") as network_call,
                ):
                    status, stdout, stderr = self.run_cli(argv, document)
                self.assertEqual(status, 2)
                self.assertEqual(stdout, "")
                self.assertIn("pr6_authority_drift", stderr)
                socket_call.assert_not_called()
                subprocess_call.assert_not_called()
                network_call.assert_not_called()

        with (
            mock.patch.object(DIRECT_OFFLINE, "OWNER_GAPS", ()),
            mock.patch.object(socket, "socket") as socket_call,
            mock.patch.object(subprocess, "run") as subprocess_call,
            mock.patch.object(urllib.request, "urlopen") as network_call,
        ):
            status, stdout, stderr = self.run_cli(["doctor"], self.profile)
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("pr6_owner_gap_drift", stderr)
        socket_call.assert_not_called()
        subprocess_call.assert_not_called()
        network_call.assert_not_called()

    def test_exact_typed_pr6_owner_gaps_and_support_cross_check(self) -> None:
        ONBOARDING._assert_pr6_non_authority()
        resource, live = DIRECT_OFFLINE.OWNER_GAPS
        candidates = (
            ("empty", ()),
            ("reordered", (live, resource)),
            (
                "resource-port-replaced",
                (
                    DIRECT_OFFLINE.OwnerGap(
                        "replacement_resource_port",
                        resource.exact_owner,
                        resource.expected_type,
                    ),
                    live,
                ),
            ),
            (
                "resource-owner-replaced",
                (
                    DIRECT_OFFLINE.OwnerGap(
                        resource.port,
                        "replacement_resource_owner",
                        resource.expected_type,
                    ),
                    live,
                ),
            ),
            (
                "live-type-replaced",
                (
                    resource,
                    DIRECT_OFFLINE.OwnerGap(
                        live.port,
                        live.exact_owner,
                        "ReplacementLiveCapability",
                    ),
                ),
            ),
            ("additional", (*DIRECT_OFFLINE.OWNER_GAPS, resource)),
            ("wrong-container-type", list(DIRECT_OFFLINE.OWNER_GAPS)),
        )
        for label, candidate in candidates:
            with self.subTest(label=label):
                with mock.patch.object(DIRECT_OFFLINE, "OWNER_GAPS", candidate):
                    with self.assertRaises(ONBOARDING.DirectOnboardingError) as raised:
                        ONBOARDING._assert_pr6_non_authority()
                self.assertEqual(raised.exception.code, "pr6_owner_gap_drift")

        with mock.patch.object(DIRECT_OFFLINE, "OwnerGap", None):
            with self.assertRaises(ONBOARDING.DirectOnboardingError) as raised:
                ONBOARDING._assert_pr6_non_authority()
        self.assertEqual(raised.exception.code, "pr6_owner_gap_drift")

        for field, replacement in (
            ("status", "replacement_status"),
            ("fallback_allowed", True),
            ("synthetic_substitute_allowed", True),
        ):
            def changed_document(
                gap: DIRECT_OFFLINE.OwnerGap,
                *,
                changed_field: str = field,
                changed_value: object = replacement,
            ) -> dict[str, object]:
                document = {
                    "port": gap.port,
                    "exact_owner": gap.exact_owner,
                    "expected_type": gap.expected_type,
                    "status": "required_exact_direct_ingress_unavailable",
                    "fallback_allowed": False,
                    "synthetic_substitute_allowed": False,
                }
                document[changed_field] = changed_value
                return document

            with self.subTest(document_field=field):
                with mock.patch.object(
                    DIRECT_OFFLINE.OwnerGap,
                    "document",
                    changed_document,
                ):
                    with self.assertRaises(ONBOARDING.DirectOnboardingError) as raised:
                        ONBOARDING._assert_pr6_non_authority()
                self.assertEqual(raised.exception.code, "pr6_owner_gap_drift")

        resource_token = ONBOARDING.OWNER_GAP_SUPPORT_TOKENS[resource.port]
        reduced_gaps = tuple(
            gap for gap in ONBOARDING.COMPOSITION_CLOSED_GAPS if gap != resource_token
        )
        with mock.patch.object(ONBOARDING, "COMPOSITION_CLOSED_GAPS", reduced_gaps):
            with self.assertRaises(ONBOARDING.DirectOnboardingError) as raised:
                ONBOARDING._assert_pr6_non_authority()
        self.assertEqual(raised.exception.code, "pr6_support_gap_drift")

        changed_tokens = copy.deepcopy(ONBOARDING.OWNER_GAP_SUPPORT_TOKENS)
        changed_tokens[resource.port] = "real_no_follow_observer"
        with mock.patch.object(
            ONBOARDING,
            "OWNER_GAP_SUPPORT_TOKENS",
            changed_tokens,
        ):
            with self.assertRaises(ONBOARDING.DirectOnboardingError) as raised:
                ONBOARDING._assert_pr6_non_authority()
        self.assertEqual(raised.exception.code, "pr6_support_gap_drift")

    def test_complete_literal_support_snapshots_reject_reviewer_drifts(self) -> None:
        ONBOARDING._assert_pr6_non_authority()
        gaps = ONBOARDING.EXPECTED_PRODUCTION_GAPS
        gap_candidates = (
            ("added", (*gaps, "future_unreviewed_gap")),
            ("deleted", gaps[1:]),
            ("reordered", (gaps[1], gaps[0], *gaps[2:])),
            ("wrong-type", list(gaps)),
        )
        for label, candidate in gap_candidates:
            with self.subTest(gaps=label):
                matrix = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
                matrix["direct_ssh_pbs"]["production_gaps"] = list(candidate)
                self.assert_sanitized_support_snapshot_drift(
                    PRODUCTION_GAPS=candidate,
                    SUPPORT_MATRIX=matrix,
                )

        statuses = ONBOARDING.EXPECTED_DIRECT_STATUSES
        status_candidates = (
            ("added", (*statuses, "future_unreviewed_status")),
            ("deleted", statuses[:-1]),
            ("reordered", tuple(reversed(statuses))),
            ("wrong-type", list(statuses)),
        )
        for label, candidate in status_candidates:
            with self.subTest(statuses=label):
                matrix = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
                matrix["direct_ssh_pbs"]["statuses"] = list(candidate)
                self.assert_sanitized_support_snapshot_drift(
                    DIRECT_STATUSES=candidate,
                    SUPPORT_MATRIX=matrix,
                )

        matrix_candidates = []
        for backend in (
            "local_gaussian",
            "slurm",
            "mcp",
            "multihop",
            "arbitrary_shell",
            "unknown",
        ):
            changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
            changed[backend]["status"] = "supported"
            matrix_candidates.append((f"{backend}-supported", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["legacy_rtwin_pbs"]["direct_cli_allowed"] = True
        matrix_candidates.append(("legacy-direct-cli", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["legacy_rtwin_pbs"]["direct_cli_allowed"] = 0
        matrix_candidates.append(("legacy-bool-lookalike", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["future_backend"] = {"status": "unsupported"}
        matrix_candidates.append(("additional-row", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed.pop("mcp")
        matrix_candidates.append(("missing-row", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["unknown"]["unexpected"] = False
        matrix_candidates.append(("additional-row-field", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["legacy_rtwin_pbs"].pop("root_policy")
        matrix_candidates.append(("missing-legacy-field", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["direct_ssh_pbs"].pop("live_ready")
        matrix_candidates.append(("missing-direct-field", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["direct_ssh_pbs"]["production_gaps"] = list(reversed(gaps))
        matrix_candidates.append(("reordered-gap-list", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["direct_ssh_pbs"]["backend_supported"] = True
        matrix_candidates.append(("direct-backend-supported", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["direct_ssh_pbs"]["backend_supported"] = 0
        matrix_candidates.append(("direct-bool-lookalike", changed))
        changed = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        changed["direct_ssh_pbs"]["statuses"] = list(
            reversed(ONBOARDING.EXPECTED_DIRECT_STATUSES)
        )
        matrix_candidates.append(("reordered-status-list", changed))
        for label, candidate in matrix_candidates:
            with self.subTest(matrix=label):
                self.assert_sanitized_support_snapshot_drift(
                    SUPPORT_MATRIX=candidate,
                )

    def test_coherent_status_and_matrix_drift_fails_sanitized_before_output(self) -> None:
        statuses = (*ONBOARDING.EXPECTED_DIRECT_STATUSES, "future_unreviewed_status")
        matrix = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
        matrix["direct_ssh_pbs"]["statuses"] = list(statuses)
        for argv, document in (
            (["init", "direct-profile-001"], None),
            (["validate"], self.profile),
            (["doctor"], self.profile),
        ):
            with self.subTest(argv=argv):
                with (
                    mock.patch.object(ONBOARDING, "DIRECT_STATUSES", statuses),
                    mock.patch.object(ONBOARDING, "SUPPORT_MATRIX", matrix),
                    mock.patch.object(socket, "socket") as socket_call,
                    mock.patch.object(subprocess, "run") as subprocess_call,
                    mock.patch.object(urllib.request, "urlopen") as network_call,
                ):
                    status, stdout, stderr = self.run_cli(argv, document)
                self.assertEqual(status, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    stderr,
                    "ERROR pr6_support_snapshot_drift: "
                    "the offline direct-backend support snapshot changed\n",
                )
                socket_call.assert_not_called()
                subprocess_call.assert_not_called()
                network_call.assert_not_called()

    def test_full_matrix_row_drifts_fail_sanitized_before_doctor_output(self) -> None:
        cases = (
            ("unknown", "status", "supported"),
            ("local_gaussian", "status", "supported"),
            ("legacy_rtwin_pbs", "direct_cli_allowed", True),
        )
        for backend, field, value in cases:
            matrix = copy.deepcopy(ONBOARDING.EXPECTED_SUPPORT_MATRIX)
            matrix[backend][field] = value
            with self.subTest(backend=backend, field=field):
                self.assert_sanitized_support_snapshot_drift(
                    SUPPORT_MATRIX=matrix,
                )

    def test_parser_and_api_have_no_root_path_env_command_or_callback_surface(self) -> None:
        parser = ONBOARDING.build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if type(action).__name__ == "_SubParsersAction"
        )
        self.assertEqual(tuple(subparsers.choices), ("init", "validate", "doctor"))
        option_strings = {
            option
            for candidate in (parser, *subparsers.choices.values())
            for action in candidate._actions
            for option in action.option_strings
        }
        self.assertFalse(
            option_strings.intersection(
                {
                    "--root",
                    "--path",
                    "--input",
                    "--output",
                    "--env",
                    "--backend",
                    "--command",
                    "--callback",
                    "--shell",
                }
            )
        )
        self.assertEqual(
            tuple(inspect.signature(ONBOARDING.build_unreviewed_template).parameters),
            ("profile_id",),
        )
        self.assertEqual(
            tuple(inspect.signature(ONBOARDING.validate_direct_profile).parameters),
            ("document",),
        )
        self.assertEqual(
            tuple(inspect.signature(ONBOARDING.doctor_summary).parameters),
            ("document",),
        )

        tree = ast.parse((SCRIPTS / "direct_onboarding.py").read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "os",
            "socket",
            "subprocess",
            "urllib",
            "http",
            "paramiko",
            "legacy_rtwin_pbs",
            "platform_contracts",
        ):
            self.assertNotIn(forbidden, imports)

    def test_declared_root_is_part_of_profile_v3_hash(self) -> None:
        changed = copy.deepcopy(self.profile)
        changed["declared_allowed_root"] = "/reviewed/different-root"
        changed = ROOT_OWNER._finalize(changed, "profile_payload_sha256")
        validated = ROOT_OWNER.validate_direct_execution_profile(changed)
        self.assertNotEqual(
            validated["profile_payload_sha256"],
            self.profile["profile_payload_sha256"],
        )
        original_without_root = copy.deepcopy(self.profile)
        original_without_root.pop("declared_allowed_root")
        with self.assertRaises(ROOT_OWNER.DirectRootOwnerError):
            ROOT_OWNER.validate_direct_execution_profile(original_without_root)

    def test_old_unknown_and_unsupported_profiles_fail_without_legacy_fallback(self) -> None:
        for schema in (
            "auto-g16-execution-profile/1",
            "auto-g16-execution-profile/2",
        ):
            with self.subTest(schema=schema):
                status, stdout, stderr = self.run_cli(
                    ["validate"],
                    {"schema": schema, "backend_kind": "legacy_rtwin_pbs"},
                )
                self.assertEqual(status, 2)
                self.assertEqual(stdout, "")
                self.assertIn("legacy_profile_requires_legacy_owner", stderr)
                self.assertIn("no direct fallback", stderr)

        for document in (
            {"schema": "auto-g16-execution-profile/4"},
            {"schema": "unknown"},
            {"backend_kind": "direct_ssh_pbs"},
        ):
            with self.subTest(document=document):
                status, stdout, stderr = self.run_cli(["validate"], document)
                self.assertEqual(status, 2)
                self.assertEqual(stdout, "")
                self.assertIn("unsupported_profile_schema", stderr)

        wrong_backend = copy.deepcopy(self.profile)
        wrong_backend["backend_kind"] = "legacy_rtwin_pbs"
        wrong_backend = ROOT_OWNER._finalize(wrong_backend, "profile_payload_sha256")
        status, stdout, stderr = self.run_cli(["doctor"], wrong_backend)
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("invalid_direct_profile", stderr)
        self.assertNotIn("legacy", stdout)

    def test_doctor_never_leaks_profile_or_host_identity_values(self) -> None:
        root = self.profile["declared_allowed_root"]
        status, stdout, stderr = self.run_cli(["doctor"], self.profile)
        self.assertEqual((status, stderr), (0, ""))
        summary = json.loads(stdout)
        self.assertEqual(
            summary["profile_hash_prefix"],
            self.profile["profile_payload_sha256"][: ONBOARDING.HASH_PREFIX_LENGTH],
        )
        self.assertNotIn(root, stdout)
        self.assertNotIn(self.profile["profile_id"], stdout)
        self.assertNotIn(self.profile["profile_payload_sha256"], stdout)
        for forbidden_value in (
            "[PRIVATE_HOST]",
            "[PRIVATE_USER]",
            "[PRIVATE_IP]",
            "[PRIVATE_PATH]",
            "[PRIVATE_KEY]",
            "[PRIVATE_TOKEN]",
        ):
            hostile = copy.deepcopy(self.profile)
            hostile["unexpected_private_value"] = forbidden_value
            status, stdout, stderr = self.run_cli(["doctor"], hostile)
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertNotIn(forbidden_value, stderr)
            self.assertIn("invalid_direct_profile", stderr)

    def test_status_and_gap_matrix_match_approved_pr6_non_authority(self) -> None:
        direct = ONBOARDING.SUPPORT_MATRIX["direct_ssh_pbs"]
        self.assertEqual(
            direct["statuses"],
            ["offline_synthetic", "production_blocked", "live_not_ready"],
        )
        self.assertFalse(direct["backend_supported"])
        self.assertFalse(direct["live_ready"])
        self.assertEqual(direct["trusted_server_local_session"], "offline_fake_local_only")
        self.assertEqual(
            tuple(direct["composition_closed_gaps"]),
            ONBOARDING.COMPOSITION_CLOSED_GAPS,
        )
        self.assertFalse(direct["arbitrary_same_process_reflection_isolated"])
        self.assertFalse(direct["production_closure"])
        self.assertTrue(DIRECT_OFFLINE.AUTHORITY["synthetic_only"])
        self.assertFalse(DIRECT_OFFLINE.AUTHORITY["backend_supported"])
        self.assertFalse(DIRECT_OFFLINE.AUTHORITY["live_ready"])
        self.assertEqual(
            tuple(direct["production_gaps"]),
            ONBOARDING.PRODUCTION_GAPS,
        )
        self.assertNotIn(
            "real_no_follow_observer",
            direct["production_gaps"],
        )
        for backend in (
            "local_gaussian",
            "slurm",
            "mcp",
            "multihop",
            "arbitrary_shell",
        ):
            self.assertEqual(ONBOARDING.SUPPORT_MATRIX[backend]["status"], "unsupported")
        self.assertEqual(ONBOARDING.SUPPORT_MATRIX["unknown"]["status"], "fail_closed")

        text = DOC.read_text(encoding="utf-8")
        for marker in (
            *ONBOARDING.DIRECT_STATUSES,
            *ONBOARDING.COMPOSITION_CLOSED_GAPS,
            *ONBOARDING.PRODUCTION_GAPS,
        ):
            self.assertIn(marker, text)
        for marker in (
            "existing_production_path_not_authorized_by_this_command",
            "platform_contracts",
            "fixed_legacy_root",
            "direct_cli_allowed=false",
            "backend_supported=false",
            "live_ready=false",
            "unsupported",
            "fail_closed",
        ):
            self.assertIn(marker, text)
        self.assertIn("`backend_supported=false`", text)
        self.assertNotIn("`real_no_follow_observer`", text)
        self.assertNotIn("direct backend is production-ready", text.lower())

    def test_migration_guide_forbids_upgrade_rehash_backfill_and_root_override(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        for schema in (
            "auto-g16-execution-profile/1",
            "auto-g16-execution-profile/2",
            "auto-g16-execution-profile/3",
        ):
            self.assertIn(schema, text)
        for required in (
            "never auto-upgrade",
            "No rehash/backfill",
            "Must never be reused or recomputed as migration",
            "Root cannot come from a flag, environment variable, runtime setting, caller",
            "Historical `/1` and `/2` artifacts replay unchanged",
            "Required human review",
            "Blockers",
        ):
            self.assertIn(required, text)

    def test_issue_template_is_static_and_forbids_sensitive_categories(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        template = text.split("## Static redacted issue template", 1)[1]
        self.assertIn("static checklist, not an automatic sanitizer", template)
        for forbidden_category in (
            "host",
            "user name",
            "IP address",
            "SSH config",
            "private path",
            "server root",
            "raw profile",
            "raw authorization",
            "raw scientific input",
            "raw log",
            "Gaussian output",
            "checkpoint",
            "job ID",
            "private key",
            "password",
            "token",
        ):
            self.assertIn(forbidden_category, template)
        for allowed_category in (
            "Auto-G16 version",
            "OS family only",
            "Backend enum",
            "Command enum",
            "Error code only",
            "hash prefix",
            "doctor redacted summary",
        ):
            self.assertIn(allowed_category, template)
        self.assertIn("correlation risk", template)

    def test_package_links_naming_and_frozen_legacy_bytes(self) -> None:
        package = SKILL_PACKAGE.package_files_with_supplements(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            package[Path("scripts/direct_onboarding.py")],
            SCRIPTS / "direct_onboarding.py",
        )
        self.assertEqual(
            package[Path("references/direct-onboarding-support.md")],
            DOC,
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-rtwin-pbs/scripts/direct_onboarding.py").exists()
        )
        self.assertTrue(DOC.read_text(encoding="utf-8").startswith("# Auto-G16"))

        frozen = {
            "scripts/platform_contracts.py": "7b4ea8e7922ce9ca868ee015170664efd85147767c6487b894aaf489bf5fc7b9",
            "scripts/legacy_root_authority_contract.py": "8c0c2eab59087f108a0b35574fcd9edf1ed3665457a164c866d28f8eaf98c0b1",
            "scripts/protected_production_ingress_contract.py": "0cb8d84271968dbc5641a2a2f625d3f3a950a793952104f773c73f71ff45e2df",
            "scripts/protected_production_factory_consumer.py": "5db1043a9107cc11843d2a7284ab802200b2502a77807ed8e8e9c38f1786ddf7",
            "skills/auto-g16-rtwin-pbs/scripts/execution_facade.py": "e7a3127b4729ee1db99fa9691c0d0b7f00cd953e179d750f3af5ee99cd4dcdc3",
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py": "3471014b9358380938e98839aaacb9cd3f9f20146fc79c1a9738483021c2cb8e",
        }
        for relative, expected in frozen.items():
            with self.subTest(relative=relative):
                payload = (ROOT / relative).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected)
        legacy = (SCRIPTS / "legacy_root_authority_contract.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('FIXED_REMOTE_ROOT = "/home/user100/SDL"', legacy)

    def test_cli_snapshots_and_exit_codes_are_closed(self) -> None:
        status, stdout, stderr = self.run_cli(["init", "direct-profile-001"])
        self.assertEqual((status, stderr), (0, ""))
        template = json.loads(stdout)
        self.assertEqual(
            set(template),
            {
                "schema",
                "profile_id",
                "target_profile_schema",
                "backend_kind",
                "status",
                "support_statuses",
                "required_owner_inputs",
                "required_human_review",
                "root_must_be_backend_owned_profile_field",
                "root_must_be_profile_hash_bound",
                "root_override_allowed",
                "schema_valid_is_capability",
                "backend_supported",
                "live_ready",
                "template_payload_sha256",
            },
        )
        self.assertEqual(template["status"], "unreviewed_non_authorizing_template")
        self.assertFalse(template["root_override_allowed"])
        self.assertFalse(template["backend_supported"])
        self.assertFalse(template["live_ready"])

        status, stdout, stderr = self.run_cli(["validate"], self.profile)
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(
            set(json.loads(stdout)),
            {
                "schema",
                "command",
                "profile_schema",
                "profile_id",
                "profile_payload_sha256",
                "statuses",
                "backend_supported",
                "live_ready",
                "offline_only",
                "capability_issued",
            },
        )

        for argv, document, error_code in (
            (["validate"], b"", "invalid_input_size"),
            (["doctor"], b'{"schema":"x","schema":"y"}', "duplicate_json_key"),
            (["init", "INVALID PROFILE"], None, "invalid_profile_id"),
        ):
            with self.subTest(argv=argv):
                status, stdout, stderr = self.run_cli(argv, document)
                self.assertEqual(status, 2)
                self.assertEqual(stdout, "")
                self.assertIn(error_code, stderr)

        help_text = ONBOARDING.build_parser().format_help()
        self.assertIn("{init,validate,doctor}", help_text)
        self.assertIn("Offline-only onboarding", help_text)
        self.assertNotIn("--root", help_text)
        self.assertNotIn("--output", help_text)


if __name__ == "__main__":
    unittest.main()
