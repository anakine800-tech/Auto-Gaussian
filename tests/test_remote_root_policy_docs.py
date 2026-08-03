from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def normalized(path: str) -> str:
    return re.sub(r"\s+", " ", (ROOT / path).read_text(encoding="utf-8"))


class RemoteRootPolicyDocumentationTests(unittest.TestCase):
    def test_stable_identity_is_separate_from_fresh_observation(self) -> None:
        policy = normalized("docs/v2.6-remote-root-policy.md")

        required = (
            "StableRootIdentityEvidence",
            "must not contain observation time, expiry, nonce, receipt ID",
            "stable-root-identity-evidence hash",
            "It does not and cannot pre-bind a future fresh-receipt hash",
            "FreshRootObservationReceipt",
            "Time, expiry and nonce exist only in this fresh receipt",
            "receipt references and proves equality with the approved stable evidence",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, policy)

    def test_mutation_consumes_the_verified_identity_without_path_reopen(self) -> None:
        policy = normalized("docs/v2.6-remote-root-policy.md")

        required = (
            "non-copyable, single-use descriptor- or capability-bound value",
            "consume that exact capability in the same atomic operation",
            "descriptor-relative no-follow operations",
            "must not reopen, re-resolve or substitute a path after the check",
            "stop before reservation, claim, write, transfer or any other remote effect",
            "If the backend cannot prove this check-to-use closure, it must reject the operation",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, policy)

    def test_repository_rule_and_rfc_preserve_the_same_fail_closed_split(self) -> None:
        agents = normalized("AGENTS.md")
        rfc = normalized("docs/v2.6-platform-portability-rfc.md")

        for phrase in (
            "stable evidence that excludes observation time and expiry",
            "fresh, time-bounded no-follow observation receipt",
            "single-use descriptor- or capability-bound handle",
            "without reopening a path",
            "zero remote effect",
        ):
            with self.subTest(document="AGENTS.md", phrase=phrase):
                self.assertIn(phrase, agents)

        for phrase in (
            "StableRootIdentityEvidence",
            "FreshRootObservationReceipt",
            "build_stable_root_identity() -> StableRootIdentityEvidence",
            "observe_fresh_root_once(",
            "descriptor_capability: SingleUseWorkspaceDescriptorCapability",
            "single-use descriptor/capability",
            "不得在检查后按 path reopen/re-resolve/substitute",
            "reservation/claim/write/transfer/任何 remote effect 前停止",
        ):
            with self.subTest(document="RFC", phrase=phrase):
                self.assertIn(phrase, rfc)
        self.assertNotIn("validate_root() -> CanonicalRootEvidence", rfc)


if __name__ == "__main__":
    unittest.main()
