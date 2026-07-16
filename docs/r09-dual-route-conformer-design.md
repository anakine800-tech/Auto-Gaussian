# Auto-G16 dual-route conformer discovery design

## Ownership

`auto-g16-view-rt-win` remains the R08 owner for reviewed 2D-to-3D conversion,
stereochemistry-preserving conformer preparation, explicit selection, and
visible GaussView review. `auto-g16-conformer-search` consumes an exact
immutable R08 handoff and owns only offline discovery planning, supplied
candidate auditing, cross-route structural comparison, negative evidence, and
candidate-only handoff.

No component in this feature installs or executes xTB, CREST, Gaussian, PBS,
SSH, or GaussView. No artifact authorizes a calculation.

## Architecture

The feature uses four preregistered adapters:

- A1: CREST enhanced-sampling interface;
- A2: native xTB-MD heating/holding/cooling interface;
- B1: ETKDGv3 plus MMFF94s-or-UFF interface;
- B2: configuration-driven interaction/mechanism orientation interface.

Adapters retain reviewed argv templates, environment, seeds, dependencies,
and the shared xTB protocol while fixing `execution_allowed: false`. The
planner does not manufacture version-specific xTB or CREST syntax.

## Offline artifact chain

1. reviewed conformer-search request;
2. dependency diagnostic and six-component freedom analysis;
3. non-executable, category-stratified search plan;
4. externally supplied candidate observations;
5. candidate validity and negative-evidence ledger;
6. cross-route ensemble manifest with comparisons, clusters, and medoids;
7. separately reviewed candidate-only downstream handoff.

Every derived artifact binds exact files by SHA-256. The request validator
resolves the reviewed R08 file, rejects a missing or symlinked leaf, verifies
its bytes and schema, and the plan validator rebuilds the full plan from the
exact bound request before any candidate audit. A recomputed payload hash
cannot legitimize altered constraints or authority fields. New revisions use
an existing, non-symlink predecessor plus exact file and payload hashes through
`supersedes`; writers refuse overwrite.

## Freedom and quota contract

The planner records

`F = (N_rot, N_ring, D_relative, N_weak, N_face, N_symmetry)`

where `D_relative = max(0, 6*(fragment_count-1)-relative_constraints)` is only
a search-complexity indicator. Route recommendations follow the reviewed
35/65, 50/50, 67/33, and 75/25 policy bands, but plans lock only explicit
reviewed weights. Each category receives A/B and A1/A2/B1/B2 quotas. Quota
credit means legal, xTB-converged, route-internally independent structures,
never raw frames.

## Legality and similarity

The audit compares atom inventory/order/map, graph, explicit-H ownership,
charge, multiplicity, stereochemistry, fragments, state labels, coordinates,
required/forbidden bonds, configured descriptor ranges, association state,
non-target transfer, and supplied optimization status. State changes are
negative evidence or new hypotheses; they never silently alter the original
state.

The composite distance includes mapped and user-supplied symmetry-permuted
heavy-atom RMSD, key distances, periodic torsions, contact fingerprints,
fragment, aromatic, and custom descriptors. Different category labels cannot
merge. Boundary, symmetry, descriptor-conflicting, or reviewer-selected pairs
enter an independent-backend queue. Cluster medoids minimize summed composite
distance with deterministic candidate-ID tie-breaking.

## Acceptance coverage

- clean isolated worktree and unique `codex/` branch;
- new repository-owned `auto-g16-conformer-search` Skill;
- closed versioned contracts and immutable bindings;
- generic configuration with no reaction-specific atom IDs or molecule names;
- synthetic rigid, flexible, symmetric, multifragment, ion-pair, category,
  mapping-drift, graph-change, H-transfer, dissociation, collision, symmetry,
  and missing-dependency fixtures;
- pure-offline unit, CLI integration, schema, packaging, and full repository
  regression tests;
- no external chemistry execution, deployment, push, PR, merge, or live smoke.

## Known limitations

- Version and capability probes are deliberately not executed in this phase;
  discovered software remains version-unknown until separately reviewed.
- Symmetry permutations and chemical descriptors are reviewed inputs; the
  core does not infer equivalence classes, faces, aromatic rings, contacts, or
  mechanism categories.
- The standard-library RMSD backend supports deterministic mapped alignment;
  queued spyrmsd/RDKit review is not marked complete without external evidence.
- Candidate observations can record xTB convergence and route-local energy,
  but this feature does not independently reproduce those external facts.
- No force-field, xTB, annealing, or mixed-software energy is used for final
  ranking. Final thermodynamics remain a separately approved common DFT task.
