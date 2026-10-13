#!/usr/bin/env python3
"""Real RDKit structure, conformer, and depiction smoke coverage."""

from __future__ import annotations

import os
import unittest


try:
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdDepictor
except ImportError:  # pragma: no cover - exercised by core-only environments
    Chem = None
    AllChem = None
    rdDepictor = None


class RdkitChemistrySmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        if Chem is None:
            if os.environ.get("AUTO_G16_REQUIRE_RDKIT") == "1":
                self.fail("RDKit is required for the chemistry-dependencies smoke job")
            self.skipTest("RDKit is optional in the core profile")

    def test_stereostructure_3d_conformer_and_2d_depiction(self) -> None:
        molecule = Chem.MolFromSmiles("C[C@H](O)C(=O)O")
        self.assertIsNotNone(molecule)
        Chem.AssignStereochemistry(molecule, force=True, cleanIt=True)
        centers = Chem.FindMolChiralCenters(molecule, includeUnassigned=True)
        self.assertEqual(len(centers), 1)
        self.assertIn(centers[0][1], {"R", "S"})

        three_dimensional = Chem.AddHs(molecule)
        parameters = AllChem.ETKDGv3()
        parameters.randomSeed = 0xA016
        self.assertEqual(AllChem.EmbedMolecule(three_dimensional, parameters), 0)
        self.assertIn(AllChem.UFFOptimizeMolecule(three_dimensional, maxIters=200), (0, 1))
        conformer = three_dimensional.GetConformer()
        self.assertTrue(conformer.Is3D())
        self.assertGreater(
            max(abs(conformer.GetAtomPosition(index).z) for index in range(three_dimensional.GetNumAtoms())),
            1e-3,
        )

        depiction = Chem.Mol(molecule)
        rdDepictor.Compute2DCoords(depiction)
        depiction_conformer = depiction.GetConformer()
        self.assertFalse(depiction_conformer.Is3D())
        self.assertTrue(
            any(
                abs(depiction_conformer.GetAtomPosition(index).x) > 1e-6
                or abs(depiction_conformer.GetAtomPosition(index).y) > 1e-6
                for index in range(depiction.GetNumAtoms())
            )
        )
        self.assertIn("M  END", Chem.MolToMolBlock(depiction))


if __name__ == "__main__":
    unittest.main()
