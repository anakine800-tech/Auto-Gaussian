# Conformer workflow

## Generation contract

- Require one connected molecular graph by default. Disconnected complexes need explicit permission and manual review of relative fragment placement.
- Preserve corrected ChemDraw explicit-H wedge/dash stereochemistry before embedding.
- Reject unassigned tetrahedral centers and conflicting or unsupported ChemDraw CFG values.
- Embed with ETKDGv3 and `enforceChirality=True`.
- Minimize with MMFF94s only when every atom is parameterized; otherwise use UFF when fully parameterized.
- Rank by force-field energy, filter by an explicit energy window, remove structures below the RMSD threshold, and cap the retained count.
- Keep force-field convergence state and warnings for every conformer.

Force-field energies are prescreening values only. They must not appear in a Gaussian energy table or be combined with DFT energies.

## Review and selection

Every generated manifest must remain `candidate_only: true` and `calculation_ready: false`. Inspect identity, charge/multiplicity, CIP centers, force-field fallback, convergence, and 3D geometry. For BINOL-, SPINOL-, BINAP-, or other atropisomeric structures, inspect axial configuration explicitly because the enumerator does not validate axial chirality.

Use `select --confirmed` to promote a reviewed candidate. Selection copies the immutable GJF/XYZ and records the source ensemble hash. It does not delete other candidates and does not authorize Gaussian submission by itself; method, basis, temperature, standard state, and resources still require calculation approval.

## Gaussian refinement

Calculate all retained candidates that could contribute materially, using the same approved Opt-Freq-single-point stack. Reject failed optimizations and structures with imaginary frequencies when modeling minima. Check whether multiple starting conformers converge to the same optimized structure before population analysis. Use composite Gaussian Gibbs energies—not force-field rankings—for final relative energies and Boltzmann populations.
