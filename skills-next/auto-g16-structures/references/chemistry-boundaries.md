# Chemistry boundaries

Adapted from [chemistry-boundaries.md（v3-frozen）](https://github.com/anakine800-tech/Auto-Gaussian/blob/v3-frozen/skills/auto-g16-view-rt-win/references/chemistry-boundaries.md). Historical attribution only; use this document for current execution, not the frozen workflow.

Ask the researcher about uncertain regioisomers, tautomers, salts, solvates,
protonation, stereochemistry, charge or multiplicity. Use the structure's formal
charge in the summary. Multiplicity must be supplied by the researcher or
`study.md`; do not infer singlet from an absence of radical flags.

Radicals, metals and coordination systems are outside this Skill. The supported
elements are H, B, C, N, O, F, Si, P, S, Cl, Br and I. The scripts reject detected
radicals, dative/unspecified bonds, unsupported elements and disconnected graphs.
A covalent drawing or XYZ may hide coordination or radical character: the LLM
must still inspect the source and intended electronic state with the researcher.

Do not infer axial chirality from an empty tetrahedral-center list. Retain and
inspect the source drawing for BINOL/BINAP/SPINOL and related atropisomers.

ETKDGv3 plus MMFF94s/UFF gives starting geometries and prescreening energies,
not proof of exhaustive sampling, a minimum, a transition state, or a method
suitable for excited states, ion pairs or unusual bonding. Boron commonly needs
UFF because MMFF lacks parameters; disclose the fallback and inspect geometry.

Atom counts must distinguish source atoms from explicit-H Cartesian atoms.
Adding H must conserve molecular formula; Cartesian rows must match the expanded
molecule. MOL/SDF roundtrip warnings matter: use the original ChemDraw source or
stereo SMILES if serialization loses stereochemistry.
