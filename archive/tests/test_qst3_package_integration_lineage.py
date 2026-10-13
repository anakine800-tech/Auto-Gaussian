import unittest
from pathlib import Path

from tests import qst3_package_integration_lineage as LINEAGE


ROOT = Path(__file__).resolve().parents[1]


class QST3PackageIntegrationLineageTests(unittest.TestCase):
    def test_terminal_validates_immutable_git_objects_and_exact_transition(self):
        owner = LINEAGE.load(ROOT)
        for relative in sorted(
            LINEAGE.PRODUCT_PATHS
            | LINEAGE.VERIFIER_PATHS
            | LINEAGE.SUPPORTING_TEST_PATHS
        ):
            with self.subTest(relative=relative):
                record = owner.records[relative]
                self.assertEqual(owner.integrate(relative, record[2]), record[5])
        self.assertNotIn(LINEAGE.HISTORICAL_PATH, owner.records)

    def test_dependency_graph_has_no_mutable_current_cycle_and_rejects_reverse_edge(self):
        edges = LINEAGE.dependency_edges()
        LINEAGE.validate_dependency_graph(edges)
        self.assertEqual(LINEAGE.active_mutable_current_cycles(edges), ())
        mutated = set(edges)
        mutated.add(
            (
                LINEAGE.TERMINAL_RELATIVE.as_posix(),
                "tests/test_direct_onboarding.py",
            )
        )
        with self.assertRaisesRegex(LINEAGE.LineageError, "active mutable current cycle"):
            LINEAGE.validate_dependency_graph(mutated)


if __name__ == "__main__":
    unittest.main()
