# Chemistry validation

## Universal checks

- Compare canonical isomeric SMILES before and after MOL/SDF serialization.
- Verify formula, formal charge, fragment count, valence, aromaticity, isotopes, and explicit hydrogens that carry meaning.
- Check requested stereochemistry independently of atom index order. CIP labels may appear in a different order than prose.
- Inspect the depiction for every fused ring, substituent position, stereobond, and charged atom.
- For familiar structures, compare the final orientation with representative literature depictions; a chemically equivalent rotation or mirror can still fail the communication requirement.

## Chiral and axial systems

- Reject unassigned (`?`) tetrahedral centers when the user requested a defined stereoisomer.
- Distinguish absolute, relative, and unspecified stereochemistry.
- Treat atropisomerism separately from tetrahedral chirality. Confirm R_a/S_a or the source's axial convention from a trusted depiction or native file.
- State when SMILES or V2000 MOL cannot faithfully preserve axial, planar, helical, or coordination stereochemistry.

## Phosphoramidite ligands

- Confirm neutral, three-coordinate P(III) unless an oxide, borane adduct, salt, or complex is requested.
- For a simple phosphoramidite, require two P-O bonds and one P-N bond; reject accidental P=O, phosphate, phosphoramidate, or phosphinite structures.
- Confirm amine substituents attach to N and both oxygens attach at the intended backbone positions.
- For BINOL-derived cyclic systems, confirm ring closure through both BINOL oxygens and separately document axial configuration.

## Organometallic and coordination structures

- Verify oxidation state assumptions, ligand charge, counterions, coordination number, donor atoms, hapticity, and bridging modes.
- Do not translate graphical coordination into ordinary covalent bonds unless the target format and chemical convention support it.
- Prefer native ChemDraw/CDXML review for dative bonds, multicenter bonding, hapticity, and annotations; label MOL/SDF exports as limited if semantics are lost.

## Salts, mixtures, polymers, and Markush structures

- Preserve dot-disconnected fragments and stoichiometry for salts/solvates.
- Do not collapse mixtures or racemates into a single defined stereoisomer.
- MOL/SDF is often inadequate for polymers, variable repeat counts, attachment points, and Markush definitions. Use native ChemDraw output when reliable tooling exists, otherwise deliver a documented review artifact rather than claiming full fidelity.
