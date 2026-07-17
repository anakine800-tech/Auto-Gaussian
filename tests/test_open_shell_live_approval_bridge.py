#!/usr/bin/env python3
"""Offline-only tests for the main-group open-shell live-approval /4 bridge."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_gaussian_auto_gate import AUTO
from tests import test_open_shell_input_receipt_bridge as receipt_fixtures


ROOT = Path(__file__).parents[1]
TRANSPORT = AUTO.transport
SCHEMA_PATH = ROOT / "contracts" / "rtwin-pbs" / "live-submission-approval-v4.schema.json"
SCHEMA_VALIDATOR = receipt_fixtures.SCHEMA_VALIDATOR


AUTHORIZATIONS = {
    "create_server_directory": True,
    "submit": True,
    "retry": False,
    "cancel": False,
    "cleanup": False,
    "delete_server_data": False,
}


class OpenShellLiveApprovalBridgeTests(unittest.TestCase):
    def build_live_chain(self, root: Path, project: str = "ohminimum") -> dict:
        chain = receipt_fixtures.OpenShellInputReceiptBridgeTests().build_receipt(root)
        validated = TRANSPORT.validate_input_approval(
            chain["receipt_path"], chain["input_path"], chain["report"], "minimum"
        )
        summary = TRANSPORT.live_approval_summary(
            project, chain["report"], None, "minimum", validated
        )
        schema, scope = TRANSPORT.expected_live_approval_scope(summary)
        approval = {
            "schema": schema,
            "decision": "approved",
            "explicit_confirmation": True,
            "scope": scope,
            "authorizations": copy.deepcopy(AUTHORIZATIONS),
        }
        approval_path = root / "live-approval-v4.json"
        approval_path.write_text(json.dumps(approval), encoding="utf-8")
        return {
            **chain,
            "input_approval": validated,
            "summary": summary,
            "approval": approval,
            "approval_path": approval_path,
        }

    def test_v4_scope_is_closed_schema_valid_and_proposal_only(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            chain = self.build_live_chain(Path(temp).resolve())
            self.assertEqual(chain["approval"]["schema"], TRANSPORT.OPEN_SHELL_LIVE_APPROVAL_SCHEMA)
            self.assertEqual(
                TRANSPORT.validate_live_approval(chain["approval_path"], chain["summary"]),
                chain["approval"],
            )
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR.validate_schema_document(schema)
            SCHEMA_VALIDATOR._validate_schema_instance(chain["approval"], schema, schema)
            proposal = TRANSPORT.live_approval_scope_proposal(chain["summary"])
            self.assertEqual(proposal["required_schema"], TRANSPORT.OPEN_SHELL_LIVE_APPROVAL_SCHEMA)
            self.assertEqual(proposal["scope_proposal"], chain["approval"]["scope"])
            self.assertTrue(proposal["proposal_only"])
            self.assertTrue(proposal["no_submission_authorization"])
            self.assertNotIn("decision", proposal)
            self.assertNotIn("authorizations", proposal)

    def test_every_v4_exact_scope_and_authorization_binding_tamper_fails(self) -> None:
        mutations = {
            "project": lambda value: value["scope"].__setitem__("project", "other"),
            "server directory": lambda value: value["scope"].__setitem__("remote_workdir", "/home/user100/SDL/other"),
            "input hash": lambda value: value["scope"].__setitem__("input_sha256", "0" * 64),
            "route": lambda value: value["scope"].__setitem__("route", "#p uhf/sto-3g opt freq"),
            "memory": lambda value: value["scope"].__setitem__("mem", "1GB"),
            "cores": lambda value: value["scope"].__setitem__("nprocshared", value["scope"]["nprocshared"] + 1),
            "charge": lambda value: value["scope"].__setitem__("charge", 1),
            "multiplicity": lambda value: value["scope"].__setitem__("multiplicity", 3),
            "work kind": lambda value: value["scope"].__setitem__("work_kind", "ordinary"),
            "receipt schema": lambda value: value["scope"]["input_approval"].__setitem__("schema", TRANSPORT.INPUT_APPROVAL_SCHEMA),
            "receipt file hash": lambda value: value["scope"]["input_approval"].__setitem__("sha256", "1" * 64),
            "receipt payload hash": lambda value: value["scope"]["input_approval"].__setitem__("payload_sha256", "2" * 64),
            "receipt input hash": lambda value: value["scope"]["input_approval"].__setitem__("input_sha256", "3" * 64),
            "receipt work kind": lambda value: value["scope"]["input_approval"].__setitem__("work_kind", "ordinary"),
            "owner name": lambda value: value["scope"]["open_shell_owner"].__setitem__("owner", "other"),
            "owner workflow": lambda value: value["scope"]["open_shell_owner"].__setitem__("workflow", "other"),
            "state review payload": lambda value: value["scope"]["open_shell_owner"].__setitem__("electronic_state_review_payload_sha256", "4" * 64),
            "handoff payload": lambda value: value["scope"]["open_shell_owner"].__setitem__("input_handoff_payload_sha256", "5" * 64),
            "audit payload": lambda value: value["scope"]["open_shell_owner"].__setitem__("input_audit_payload_sha256", "6" * 64),
            "selected option payload": lambda value: value["scope"]["open_shell_owner"].__setitem__("selected_option_payload_sha256", "7" * 64),
            "owner input hash": lambda value: value["scope"]["open_shell_owner"].__setitem__("input_sha256", "8" * 64),
            "owner route": lambda value: value["scope"]["open_shell_owner"].__setitem__("exact_route", "#p other"),
            "owner charge": lambda value: value["scope"]["open_shell_owner"].__setitem__("charge", 1),
            "owner multiplicity": lambda value: value["scope"]["open_shell_owner"].__setitem__("multiplicity", 3),
            "reference": lambda value: value["scope"]["open_shell_owner"].__setitem__("reference_family", "RO"),
            "resource tier": lambda value: value["scope"]["open_shell_owner"]["resources"].__setitem__("resource_tier", "simple"),
            "owner memory": lambda value: value["scope"]["open_shell_owner"]["resources"].__setitem__("mem_gb", 1),
            "owner cores": lambda value: value["scope"]["open_shell_owner"]["resources"].__setitem__("cores", 1),
            "owner replay": lambda value: value["scope"]["open_shell_owner"].__setitem__("owner_replay_passed", False),
            "decision": lambda value: value.__setitem__("decision", "blocked"),
            "confirmation": lambda value: value.__setitem__("explicit_confirmation", False),
            "create authority": lambda value: value["authorizations"].__setitem__("create_server_directory", False),
            "submit authority": lambda value: value["authorizations"].__setitem__("submit", False),
            "retry authority": lambda value: value["authorizations"].__setitem__("retry", True),
            "cancel authority": lambda value: value["authorizations"].__setitem__("cancel", True),
            "cleanup authority": lambda value: value["authorizations"].__setitem__("cleanup", True),
            "delete authority": lambda value: value["authorizations"].__setitem__("delete_server_data", True),
            "unknown field": lambda value: value.__setitem__("note", "not closed"),
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp).resolve()
            chain = self.build_live_chain(root)
            for index, (label, mutate) in enumerate(mutations.items()):
                with self.subTest(label=label):
                    forged = copy.deepcopy(chain["approval"])
                    mutate(forged)
                    path = root / f"tampered-{index}.json"
                    path.write_text(json.dumps(forged), encoding="utf-8")
                    with self.assertRaises((SystemExit, ValueError)):
                        TRANSPORT.validate_live_approval(path, chain["summary"])

    def test_generation_and_scientific_family_mixing_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            chain = self.build_live_chain(Path(temp).resolve())
            base = chain["summary"]

            v2_to_v3 = copy.deepcopy(chain["approval"])
            v2_to_v3["schema"] = TRANSPORT.LIVE_APPROVAL_V3_SCHEMA
            wrong_path = Path(temp) / "v2-to-v3.json"
            wrong_path.write_text(json.dumps(v2_to_v3), encoding="utf-8")
            with self.assertRaises(SystemExit):
                TRANSPORT.validate_live_approval(wrong_path, base)

            v1_to_v4 = copy.deepcopy(base)
            v1_to_v4["multiplicity"] = 1
            v1_to_v4["input_approval"] = {
                key: value
                for key, value in v1_to_v4["input_approval"].items()
                if key != "specialist_owner_binding"
            }
            v1_to_v4["input_approval"]["schema"] = TRANSPORT.INPUT_APPROVAL_SCHEMA
            v1_to_v4["input_approval"]["status"] = "validated_exact_input_approval"
            v1_schema, v1_scope = TRANSPORT.expected_live_approval_scope(v1_to_v4)
            self.assertEqual(v1_schema, TRANSPORT.LIVE_APPROVAL_V3_SCHEMA)
            wrong_v4 = {
                "schema": TRANSPORT.OPEN_SHELL_LIVE_APPROVAL_SCHEMA,
                "decision": "approved",
                "explicit_confirmation": True,
                "scope": v1_scope,
                "authorizations": copy.deepcopy(AUTHORIZATIONS),
            }
            wrong_v4_path = Path(temp) / "v1-to-v4.json"
            wrong_v4_path.write_text(json.dumps(wrong_v4), encoding="utf-8")
            with self.assertRaises(SystemExit):
                TRANSPORT.validate_live_approval(wrong_v4_path, v1_to_v4)

            for label, mutate in {
                "TS work": lambda value: value.__setitem__("work_kind", "ts_pilot"),
                "maturity mix": lambda value: value.__setitem__("scientific_maturity", {"schema": TRANSPORT.MATURITY_ACTION_V1_SCHEMA}),
                "open-shell singlet": lambda value: value.__setitem__("multiplicity", 1),
                "broken symmetry": lambda value: value["input_approval"]["specialist_owner_binding"].__setitem__("reference_family", "BS"),
                "multireference": lambda value: value["input_approval"]["specialist_owner_binding"].__setitem__("reference_family", "MR"),
                "metal owner": lambda value: value["input_approval"]["specialist_owner_binding"].__setitem__("owner", "auto-g16-metal-ts"),
            }.items():
                with self.subTest(label=label):
                    mixed = copy.deepcopy(base)
                    mutate(mixed)
                    with self.assertRaises((SystemExit, ValueError)):
                        TRANSPORT.expected_live_approval_scope(mixed)

    def test_direct_and_wrapper_dry_runs_share_v4_validator_without_network(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp).resolve()
            chain = self.build_live_chain(root)

            direct_args = TRANSPORT.build_parser().parse_args([
                "submit", str(chain["input_path"]), "--project", "ohminimum",
                "--local-dir", str(root / "direct"), "--work-kind", "minimum",
                "--input-approval-record", str(chain["receipt_path"]),
                "--approval-record", str(chain["approval_path"]), "--confirmed", "--dry-run",
            ])
            with mock.patch.object(TRANSPORT, "run", side_effect=AssertionError("network function called")) as network:
                output = StringIO()
                with redirect_stdout(output):
                    direct_args.func(direct_args)
                plan = json.loads(output.getvalue())
                self.assertFalse(network.called)
            self.assertTrue(plan["dry_run"])
            self.assertTrue(plan["live_submission_ready"])
            self.assertEqual(plan["live_approval"]["schema"], TRANSPORT.OPEN_SHELL_LIVE_APPROVAL_SCHEMA)

            proposal_args = TRANSPORT.build_parser().parse_args([
                "submit", str(chain["input_path"]), "--project", "ohminimum",
                "--local-dir", str(root / "proposal"), "--work-kind", "minimum",
                "--input-approval-record", str(chain["receipt_path"]),
                "--confirmed", "--dry-run",
            ])
            with mock.patch.object(TRANSPORT, "run", side_effect=AssertionError("network function called")) as network:
                output = StringIO()
                with redirect_stdout(output):
                    proposal_args.func(proposal_args)
                proposal_plan = json.loads(output.getvalue())
                self.assertFalse(network.called)
            self.assertFalse(proposal_plan["live_submission_ready"])
            self.assertEqual(
                proposal_plan["live_approval"]["required_schema"],
                TRANSPORT.OPEN_SHELL_LIVE_APPROVAL_SCHEMA,
            )
            self.assertEqual(
                proposal_plan["live_approval"]["scope_proposal"],
                chain["approval"]["scope"],
            )
            self.assertTrue(proposal_plan["live_approval"]["proposal_only"])

            wrapper_args = AUTO.build_parser().parse_args([
                "auto", str(chain["input_path"]), "--project", "ohminimum",
                "--local-dir", str(root / "wrapper"), "--work-kind", "minimum",
                "--input-approval-record", str(chain["receipt_path"]),
                "--approval-record", str(chain["approval_path"]), "--confirmed", "--dry-run",
            ])

            def run_direct(command: list[str], **_kwargs) -> SimpleNamespace:
                parsed = TRANSPORT.build_parser().parse_args(command[2:])
                parsed.func(parsed)
                return SimpleNamespace(returncode=0)

            with mock.patch.object(TRANSPORT, "run", side_effect=AssertionError("network function called")) as network, mock.patch.object(AUTO.subprocess, "run", side_effect=run_direct):
                output = StringIO()
                with redirect_stdout(output):
                    wrapper_args.func(wrapper_args)
                self.assertFalse(network.called)
            preflight = json.loads((root / "wrapper" / "automation_preflight.json").read_text())
            self.assertEqual(
                preflight["live_approval_requirement"]["required_schema"],
                TRANSPORT.OPEN_SHELL_LIVE_APPROVAL_SCHEMA,
            )
            self.assertTrue(preflight["live_approval_requirement"]["proposal_only"])


if __name__ == "__main__":
    unittest.main()
