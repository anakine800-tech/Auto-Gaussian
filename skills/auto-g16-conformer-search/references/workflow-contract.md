# Auto-G16 dual-route conformer-search contract

## Contents

1. Ownership and non-goals
2. Route model
3. Freedom vector and quota policy
4. Candidate legality
5. Similarity and clustering
6. Revision and execution boundary

## 1. Ownership and non-goals

This Skill begins with an immutable reviewed R08 artifact. It does not alter
that artifact, infer an active state, invent a mechanism, decide whether a
structure is a transition state, choose a production electronic-structure
method, or execute external software.

Transition metals, open shells, excited states, multireference cases, unknown
coordination, and intended connectivity changes are unsupported. Record a
blocker and delegate them to an appropriate specialist workflow.

## 2. Route model

Route A is annealing/xTB discovery:

- A1: CREST enhanced-sampling adapter;
- A2: native xTB-MD heating/holding/cooling adapter.

Route B is force-field/directed discovery followed by the same reviewed xTB
optimization layer:

- B1: unbiased ETKDGv3 with MMFF94s when complete, otherwise UFF;
- B2: configuration-driven site, face, distance, angle, torsion, aromatic,
  hydrogen-bond, ion-pair, Lewis acid/base, and fragment-orientation classes.

A1 and A2 compare sampling sensitivity, not independent electronic-structure
methods. B1 force-field energies are prescreen values only. Open Babel is not a
default second UFF production route.

Every route record contains an inert argv template, exact input/config hashes,
random seeds, expected dependency, and `execution_allowed: false`. The Skill
never runs the template.

## 3. Freedom vector and quota policy

Record

`F = (N_rot, N_ring, D_relative, N_weak, N_face, N_symmetry)`

before candidate generation. `D_relative = max(0,
6*(fragment_count-1)-relative_constraints)` is a search-complexity indicator,
not a vibrational degree-of-freedom count.

Heuristic A/B recommendations are 35/65 for low connected systems, 50/50 for
moderate flexibility, 67/33 for high flexibility or multiple fragments, and
75/25 for very high flexibility or contact ion pairs. Each route remains at
least 25%. A2 gains weight for high-flexibility, multifragment, and ion-pair
cases. These are recommendations; a plan locks only explicit reviewed weights.

Apply quotas to legal, xTB-converged, route-internally independent structures,
not raw frames. Allocate A/B and A1/A2/B1/B2 quotas inside every reviewed
category. Do not change weights after observing yield.

## 4. Candidate legality

Before quota credit, compare the candidate with the exact reviewed state:

- elements, count, map, atom order, explicit-H identity, graph, charge, spin,
  stereochemistry, fragments, state labels, and finite coordinates;
- minimum pair distance and user-required/forbidden connections;
- declared fragment association/dissociation limits;
- non-target proton/hydride ownership changes;
- xTB optimization status.

Graph/state changes become `state_changed` or `new_hypothesis_candidate`.
Never silently relabel the original state or edit a mechanism network. Preserve
every rejection in the negative-evidence ledger.

## 5. Similarity and clustering

Use a configurable composite distance over mapped heavy-atom RMSD,
symmetry-aware RMSD, key distances, periodic torsions, contact fingerprints,
fragment-relative geometry, aromatic descriptors, and custom numeric
descriptors. Lower the mapped-RMSD weight for flexible multifragment systems.

Default classification suggestions are:

- duplicate: mapped/symmetry RMSD at most 0.25 Å, key-distance RMSE at most
  0.15 Å, and identical contact fingerprint;
- highly similar: RMSD at most 0.50 Å, key-distance RMSE at most 0.25 Å, and
  contact similarity at least 0.90;
- boundary: RMSD from 0.50 through 0.75 Å;
- independent: RMSD above 0.75 Å or different category/contact class.

Project configuration may override thresholds. Different category labels are
never automatically merged. Queue threshold-boundary, symmetry-equivalent,
descriptor-conflicting, unstable multifragment, and reviewer-selected pairs
for spyrmsd or another independent backend. Absence of that backend blocks the
review; it does not trigger installation.

Choose each cluster medoid by minimum summed composite distance with candidate
ID as a deterministic tie-break. Preserve all source members and exclusion
reasons.

## 6. Revision and execution boundary

Every plan, ledger, manifest, and handoff is immutable and content-hashed. A
new revision binds the exact predecessor file hash and payload hash through
`supersedes`; it never overwrites the old revision. Failed candidates remain
addressable negative evidence.

The manifest and handoff remain candidate-only. Final structures and
thermodynamics require a separately approved common DFT Opt/Freq/single-point
workflow. UFF, xTB, annealing, route weights, and mixed software total energies
cannot replace that comparison.
