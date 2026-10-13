# Auto-G16 conformer-search artifact guide

## Contents

1. Artifact chain
2. Request essentials
3. Candidate observations
4. Manifest review

## 1. Artifact chain

The closed-shell version-one chain is:

1. `gaussian-conformer-search-request/1`
2. `gaussian-conformer-freedom-analysis/1`
3. `gaussian-conformer-search-plan/1`
4. `gaussian-conformer-candidate-set/1`
5. `gaussian-conformer-validity-ledger/1`
6. `gaussian-conformer-ensemble-manifest/1`
7. `gaussian-conformer-candidate-handoff/1`

Every derived artifact binds the exact source file SHA-256 and the source
payload SHA-256 where present.

The open-shell adapter uses the corresponding `/2` artifact identifiers.
Every V2 stage carries the same closed `open_shell_state_binding`, including
the exact accepted state-review file and payload hashes. V1 documents cannot
carry this field and retain their original closed-shell behavior.

## 2. Request essentials

Use stable IDs and zero-based `atom_index` values. Atom order and `map_id` are
immutable within one state. Define fragments explicitly. Supply bonds rather
than asking the planner to infer them. Put mechanism or interaction strata in
`categories`; do not encode them in candidate filenames.

Supply exact reviewed A/B and subroute weights, category totals, random seeds,
shared xTB settings, constraints, and similarity settings. A null or unknown
scientific value is a blocker, not a default.

For V2, derive neither multiplicity nor a reference wavefunction. Supply an
already accepted main-group state review whose candidate structure hash equals
the canonical graph hash computed from request atom order, fragment ownership,
bonds, and stereochemistry. Supply fragment-spin-coupling evidence;
`unresolved` is always a blocker.

## 3. Candidate observations

Candidate sets are observations from another authorized context. They must
record source route/subroute/category, atom records, observed bonds, fragment
membership, state labels, coordinates, optimization status, energy provenance,
contacts, key descriptors, seeds, argv, software path/version, and input hash.
An energy may be retained as route-local provenance but is never used by this
Skill for thermodynamic ranking.

## 4. Manifest review

Review consensus clusters, route-unique secondary clusters, invalid entries,
medoids, merge reasons, backend-review queues, quota fulfillment, and all
blockers. A complete structural audit still does not make the manifest
calculation-ready. Create the handoff only from explicitly reviewed medoids and
retain `no_submission_authorization: true`.
