# Force-field conformer screening

Adapted from `skills/auto-g16-view-rt-win/references/conformer-workflow.md`.

After human structure confirmation, use one connected molecular graph, preserving
ChemDraw explicit-H wedge/dash stereochemistry. Unassigned tetrahedral centers
and conflicting or unsupported CFG values stop generation.

The migrated algorithm embeds with ETKDGv3 and `enforceChirality=True`, initially
prunes at 0.1 Å, and retries embedding with random coordinates if no conformers
were found. This is local geometry generation, not a remote job retry. It uses
MMFF94s when all atoms are parameterized, otherwise fully parameterized UFF.

Defaults are 50 requested conformers, seed 61453, 1000 minimization iterations,
6 kcal/mol energy window, 0.5 Å all-atom symmetry-aware best-RMSD threshold and at
most 10 retained conformers. Change `--num-conformers`, `--seed`, `--max-iters`,
`--energy-window`, `--rmsd-threshold`, or `--max-keep` deliberately. These are the
legacy screening defaults, not a claim that sampling is complete.

`conformers.xyz` contains retained explicit-H frames in increasing force-field
energy order. Each comment starts with energy in kcal/mol, then the force-field
name. `summary.json` records input identity, supplied multiplicity, parameters,
conformer IDs, absolute/relative energy, nearest kept RMSD, convergence and
warnings. A nonconverged conformer remains flagged for review. The UFF fallback
is disclosed even when minimization converges.

Inspect identity, CIP centers, source atom count, formula, explicit-H count,
force-field fallback, convergence and 3D geometry. Inspect axial configuration
separately. Pass the XYZ and its energy units to `ag dedup`; review the resulting
representative set with the researcher. Multiple representatives can proceed;
there is no single-conformer selection step.

For the T12b proposed research workflow, retain enough force-field candidates
for DFT single-point reranking before applying the optimization count limit.
The script's legacy `--max-keep 10` is not that research limit; deliberately
choose and record candidate coverage. The force-field window is not an xTB
window. See the [screening card](../../auto-g16-recipes/cards/rdkit-screen.md)
and [proposed methods](../../auto-g16-study/references/acceptance-methods.md).
Refine relevant representatives with the same selected DFT protocol. Reject
failed optimizations and inappropriate imaginary frequencies when modeling
minima. Check whether different starting conformers converge to the same
structure. Use the reviewed thermochemistry workflow for final relative Gibbs
energies and populations; do not mix force-field and DFT energies.
