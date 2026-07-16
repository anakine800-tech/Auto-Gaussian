# Auto-G16 Mechanism-Support Matrix View

Status: distinct offline downstream implementation of
`gaussian-reaction-mechanism-support-matrix/1`. It recovers the useful
row-by-evidence comparison capability formerly proposed under the colliding
`gaussian-reaction-mechanism-support/1` name, without replacing or aliasing the
merged evidence-gate contract that owns that name.

This contract grants no mechanism proof, mechanism validation, chemistry
inference, TS construction, protocol selection, calculation-DAG node,
Gaussian input, SSH/PBS action, deployment, or submission authority.

## Ownership and exact parents

`auto-g16-reaction-workflow` owns this view because it also owns the immutable
mechanism network and mechanism-support evidence gate. The builder requires:

1. one exact, non-symlinked, owner-valid
   `gaussian-reaction-mechanism-support/1` artifact;
2. the exact `gaussian-reaction-mechanism-network/1` already bound by that
   support artifact; and
3. one separate, closed
   `gaussian-reaction-mechanism-support-matrix-review/1` source bound to both
   payload hashes.

The matrix does not reopen literature evidence, replace a support record, or
recompute either evidence-gate decision. Its `evidence_gate` compatibility
view copies the owner gate status, blocker IDs, exploration-presence flag,
claim-support-presence flag, and unconditional absence of mechanism
validation. Every row repeats the exact owner edge/channel summary facts.

Every artifact reference records a deterministic path, exact file SHA-256,
byte size, schema, and canonical payload SHA-256. Standalone validation first
invokes the unchanged `mechanism_support.py` owner validator, verifies the
network is the exact network bound by that support artifact, reopens the exact
matrix review, and independently rebuilds the complete output. Rehashing an
edited view cannot forge this reconstruction.

## Matrix semantics

Rows are human-authored bounded labels for exact owner edge/channel summaries.
Columns are derived deterministically from every exact support record; the
review source cannot rename, omit, or edit them. The review must contain
exactly one cell for every row-by-support-record intersection. Every cell
retains:

- positive, negative, contradictory, inaccessible, incomplete, rejected, or
  no-evidence status;
- a bounded supports, contradicts, does-not-address, or unknown relationship;
- all nine applicability dimensions;
- mismatches, alternatives, qualitative confidence, bounded use, decision,
  blockers, and notes.

A cell whose row is the support record's own edge/channel is a native owner
cell. Its evidence status, claim relationship, and nine applicability values
must equal the owner support record. This prevents the view from weakening or
upgrading the evidence gate. Cross-row cells remain explicit human review and
never mutate the source record.

Coverage is closed: every owner edge/channel is either represented by one row
or explicitly excluded with a rationale, and absent cross-evidence must remain
an explicit cell. Unknown fields, duplicate JSON keys, non-finite numbers,
duplicate IDs, missing cells, source drift, symlinked paths, parent traversal,
and output overwrite are rejected.

## Disposition and compatibility boundary

The row dispositions `mandatory`, `optional`, `contradicted`, and `unresolved`
are comparison-view labels only. A `mandatory` or `optional` row requires
uncontradicted positive matrix evidence and, independently, the exact owner
edge/channel must already have
`hypothesis_exploration_eligible: true`. The output therefore exposes a
`downstream_reviewable_targets` entry only at that intersection.

The entry is eligible solely for another offline review. It is not a selected
mechanism, validated mechanism, TS seed, calculation target, executable DAG
node, protocol, Gaussian input, or live approval. A blocked matrix or blocked
owner evidence gate exposes no downstream-reviewable targets. Mechanism claim
support is copied as a fact and never inferred from a row disposition.

The upstream mechanism network remains unchanged with its null child binding
and historical ordering blocker. The current calculation-artifact adapter
continues to use its own `external_target_key` boundary and does not consume
this matrix. The implemented DAG owner and feature-3 target-mapping/node-update
bridge consume the exact owner `gaussian-reaction-mechanism-support/1` artifact
and their own reviewed mappings; they do not consume this matrix. This matrix
contains no `plan_id`, `node_id`, node state, dependency closure, execution
status, or mutation command. Any later matrix-to-DAG relationship requires a
separate exact reviewed contract and an immutable DAG-owned update; a matrix
row disposition is never DAG readiness.

## Supersession and PR #19 migration

Historical artifacts are never renamed or rewritten. Any experimental PR #19
document that used `gaussian-reaction-mechanism-support/1` for matrix semantics
is not valid as the merged owner evidence-gate artifact and must not be
silently reinterpreted. Migration is an explicit rebuild:

1. preserve the historical bytes and provenance outside this new lineage;
2. build or validate the canonical merged `gaussian-reaction-mechanism-support/1`
   evidence gate from its exact parents;
3. author a new matrix review bound to that exact support and network; and
4. build a new `gaussian-reaction-mechanism-support-matrix/1` artifact.

Corrections create a new matrix whose review `supersedes` binds the exact prior
matrix path and payload hash. A changed owner support artifact always requires
a new matrix. No migration changes TS-precedent, calculation-artifact, network,
or other immutable historical records.

## CLI

```bash
MATRIX_TOOL="skills/auto-g16-reaction-workflow/scripts/mechanism_support_matrix.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$MATRIX_TOOL" build mechanism-support.json \
  --review mechanism-support-matrix-review.json \
  --output mechanism-support-matrix.json

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$MATRIX_TOOL" validate mechanism-support-matrix.json
```

Both commands use only the Python standard library and perform no subprocess,
network, database, calculation, deployment, scheduler, or live action. Every
output unconditionally retains:

- `claim_ceiling: bounded_hypothesis_space_not_mechanism_proof`;
- `mechanism_proven: false`;
- `mechanism_claim_validation_present: false`;
- `calculation_ready: false`; and
- `no_submission_authorization: true`.

Named-Skill packaging includes this script and reference from the owning Skill
tree and maps both matrix schemas through the closed
`deployment-package.json` reaction-workflow contract directory. A deployed
matrix validation also requires the separately owned deployed
`auto-g16-knowledge-base` and `auto-g16-reaction-literature` dependencies used
by the unchanged mechanism-support owner validator; packaging does not copy or
fork those validators into this Skill.
