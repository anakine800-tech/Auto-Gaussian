# Auto-G16 Mechanism-Support Matrix Contract

Status: implemented offline downstream sidecar for
`gaussian-reaction-mechanism-support/1`. This contract grants no mechanism
proof, TS construction, protocol selection, calculation-DAG, Gaussian, SSH,
PBS, deployment, or submission authority.

## Ownership and immutable inputs

`auto-g16-reaction-workflow` owns the sidecar because it validates rows against
one exact finalized `gaussian-reaction-mechanism-network/1` and its complete W1
chain. It consumes, but does not mutate, finalized literature evidence and one
reviewed `auto-g16-knowledge-snapshot/1`.

The builder requires:

- the finalized mechanism network;
- finalized `gaussian-reaction-literature-evidence/1` with complete W1 and
  knowledge-snapshot bindings;
- the exact reviewed knowledge snapshot; and
- a separate `gaussian-reaction-mechanism-support-review/1` source.

The literature evidence intentionally retains
`promotable_to_mechanism_support: false`. The separate review source must
acknowledge that gate and make every promotion decision explicitly. It cannot
change the literature record or turn metadata, an inaccessible source, or an
unlocated claim into evidence.

Every structured binding in the output records `path`, exact file SHA-256,
`size_bytes`, `schema`, and canonical payload SHA-256. Validation rejects
symlinks, missing or drifting files, duplicate JSON keys, non-finite values,
unknown fields, invalid or duplicate IDs, noncanonical output ordering,
rehashed output tampering, and overwrite. Output creation uses an exclusive
new-file write and also refuses dangling symlinks. Literature payloads use their
existing no-trailing-newline canonical hash; W1, network, knowledge, support,
and review-source payloads use the project canonical JSON form with a trailing
newline.

The bound candidate ledger must retain the production search-plan/retrieval,
ranking, counts, candidate, W1/knowledge, blocker, and safety fields. Its
W1/knowledge bindings, W2 status, and promotion blockers must exactly equal the
finalized evidence record before the network chain is checked. Source anchors
are limited to the primary-source types accepted by the literature validator;
metadata snippets cannot be promoted by setting a review boolean.

## Reviewed matrix source

The review source binds the exact network, W1, knowledge-snapshot, and
literature-evidence payload hashes. It contains:

- one evidence column for every finalized `(candidate_id, evidence_category)`
  claim;
- stable local `claim_id` and `anchor_id` values mapped one-to-one to the exact
  finalized claim and each exact source-location index;
- rows referencing real network `state_id` and/or `edge_id` values;
- exactly one cell for every row-by-column intersection;
- explicit state/edge exclusions with rationales so every network target is
  accounted for; and
- one explicit promotion review for every row.

An accepted evidence-column promotion requires `source_reports`, checked
primary evidence, an existing source location, a finalized literature decision
bounded to `mechanism_support`, and a separate support-review rationale. Other
claims remain mapped as retained, rejected, or blocked; they are never dropped
silently.

This artifact permits only `mechanism_support`, `discovery_only`, and
`not_applicable_to_target` bounded uses. TS-topology, geometry-seed, and
protocol-candidate uses belong to separate downstream contracts, including the
implemented non-promotable TS-precedent map, and cannot be exposed by a support
column or cell. Contradictory cells require the same reviewed direct/analogous and
experimental/computational classification floor as positive cells.

Each cell retains:

- `positive`, `negative`, `contradictory`, `inaccessible`, `incomplete`,
  `rejected`, or `no_evidence` status;
- a bounded supported, contradicted, non-addressing, or unknown claim;
- direct/analogous and experimental/computational classifications;
- all nine applicability dimensions with `exact`, `close`, `remote`,
  `contradictory`, `unknown`, or `not_applicable`, a rationale, and only source
  anchors from its own column;
- mismatches, alternative explanations, confidence, reviewer decision,
  bounded use, notes, and explicit blockers.

Blockers preserve the vocabulary in `literature-evidence-design.md`, including
search/access, unavailable primary/SI evidence, incomplete computational
details, unavailable coordinates, ambiguous mapping, remote analogy,
contradiction, missing path validation, nontransferable methods, and blocked
candidate construction.

## Row disposition and downstream boundary

The builder accepts a row disposition only when it is consistent with reviewed
cells and the explicit promotion review:

- `mandatory` or `optional` requires positive promoted support and no retained
  contradictory cell;
- `contradicted` requires retained contradiction and no retained positive cell;
  and
- `unresolved` covers no positive support or mixed positive/contradictory
  evidence.

Only edge IDs from `mandatory` or `optional` rows appear in the local
`downstream_reviewable_edge_ids` list. That list means “eligible for a later
offline review,” not selected mechanism, TS seed, calculation task, or job.
A blocked top-level review emits no downstream-reviewable edge IDs. The output
always retains:

- `claim_ceiling: bounded_hypothesis_space_not_mechanism_proof`;
- `mechanism_proven: false`;
- `calculation_ready: false`; and
- `no_submission_authorization: true`.

## Non-circular pairing and supersession

Version-1 mechanism networks remain immutable with `mechanism_support: null`,
empty edge `support_claim_ids`, and their historical
`mechanism_support_unavailable` blocker. Writing the support hash back into the
network would invalidate the exact network hash already bound by the support
artifact and create a circular dependency.

A later orchestrator must validate and consume the exact `(network, support)`
pair. It may recognize the sidecar as downstream evidence review while leaving
the network payload and gate status unchanged. It must never describe the pair
as mechanism proof.

A correction creates a new support sidecar with an explicit full binding to
the prior sidecar in `supersedes`. A changed network always requires a new
support artifact. Old network and support files are never rewritten. When
multiple sidecars exist without an explicit supersession link, consumers must
treat the choice as ambiguous rather than select by timestamp.

## CLI

```bash
SUPPORT_TOOL="skills/auto-g16-reaction-workflow/scripts/mechanism_support.py"

python3 "$SUPPORT_TOOL" build mechanism-network.json \
  literature-evidence-final.json knowledge-snapshot.json \
  --review mechanism-support-review.json \
  --output mechanism-support.json

python3 "$SUPPORT_TOOL" validate mechanism-support.json
```

Both commands are standard-library-only and offline. Neither command searches
literature, imports knowledge records, invokes a subprocess, or performs a live
action.
