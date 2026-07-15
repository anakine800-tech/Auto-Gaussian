# Auto-G16 calculation DAG and study-index contract

Status: smallest offline planning and resume-view slice. This contract creates
`gaussian-reaction-calculation-plan/1` and
`gaussian-reaction-study-index/1`. It does not build a geometry, select a
protocol, render a Gaussian input, submit or monitor a job, retry, cancel,
delete data, or grant calculation authority.

## Exact immutable bindings

Every bound JSON artifact uses exactly these fields:

```json
{
  "path": "relative/path.json",
  "sha256": "exact-file-sha256",
  "size_bytes": 123,
  "schema": "versioned-schema-name/1",
  "payload_sha256": "canonical-payload-sha256"
}
```

The builder and validator require a portable relative path with no `..`,
resolve it against the owning artifact, and require every bound top-level JSON
file to remain inside that artifact root. They reject absolute paths, root
escape, a missing file, and parent or leaf symlinks, then verify the byte size,
raw file SHA-256, schema discriminator, and canonical payload SHA-256. Plan and
index files therefore share one artifact root. Validation uses strict JSON
loading, rejects duplicate keys and non-finite values, and refuses hash drift.
Matching only the payload hash is insufficient because whitespace or other raw
file changes must also remain visible.

An output parent must already exist as a real directory. The CLI never creates
an output directory, follows a caller-controlled output symlink, or replaces an
existing or dangling-symlink leaf. A normal root-owned operating-system path
alias outside the artifact contract may be canonicalized, but every component
inside the caller's artifact path is checked and must not be a symlink.

A calculation plan binds the exact W1 intake, species registry, condition
model, finalized W3 mechanism network, immutable plan-review source, and every
superseded plan. `mechanism_support` and `ts_precedent_map` are nullable exact
bindings. Their absence creates explicit blockers and cannot be treated as an
empty successful review. A supplied mechanism-support artifact must pass the
origin evidence-gate owner validator and bind the exact selected intake,
registry, condition model and mechanism network by path, file hash, byte size
and payload hash. Owner eligibility remains scoped to an exact edge and
stereochemical channel. Calculation-plan review `/1` has only `edge_ids`, so
the DAG deliberately retains `mechanism_support_channel_mapping_missing` and
does not reduce channel-specific evidence to an edge-wide readiness result.
A bound support artifact is considered owner-promotable only when its review
decision is exactly `accepted`, its gate is `reviewed`, and its owner blocker
list is empty. A `blocked` or `reviewed_with_blockers` artifact retains the
network availability blocker, propagates every normalized owner blocker plus
`mechanism_support_not_promotable`, and makes the study index direct the user
back to the owner gate rather than to channel mapping.
A supplied TS-precedent map also passes its owner validator and must bind the
same exact W1/network/support parents. The DAG accepts coverage only for a
record or de novo seed plan whose reviewed disposition is
`accepted_for_candidate_construction` and whose local promotion requirements
are complete and owner gate is `candidate_construction_eligible`. Missing
coverage remains an edge-target blocker. The independent channel-mapping gate
still prevents validated precedent coverage from making a node executable or
calculation-ready. Presence or a self-consistent payload hash alone never
promotes support or precedent.

The selected W1 and W3 artifacts must also form one exact immutable chain. The
registry's intake reference, the condition model's intake/registry references,
and the mechanism network's W1 references must match the selected artifacts by
both file and payload SHA-256. Independently valid revisions with the same
`study_id` cannot be mixed.

The builder never changes an upstream artifact. Corrections and expanded work
are new immutable calculation plans linked through `superseded_plans` and
explicit node supersessions. Output overwrite is forbidden.

## Closed calculation-node semantics

The review explicitly authors stable `plan_id` and `node_id` values. The
builder never derives chemical steps, candidates, or methods from the mechanism
network. It normalizes ID-keyed collections and independently derives the
topological order, readiness, coverage, and blockers.

The closed node-kind inventory is:

- `minimum`, `conformer`, and `complex` for reviewed structural targets;
- `ts_candidate` and `ts_freq` for proposed saddle searches and their
  stationary-point/frequency stage;
- `irc_forward`, `irc_reverse`, and `endpoint` for separately represented path
  directions and endpoint work;
- `single_point`, `thermochemistry`, and `sensitivity` for later explicitly
  reviewed analysis stages.

These names are bookkeeping kinds, not instructions to a runtime. A
`ts_candidate` does not assert that a saddle exists; `ts_freq` does not accept
an imaginary mode; and an IRC or endpoint node does not claim path validation.

Each target lists exact mechanism state, edge, network, reference-basin and
state-qualified atom references. Unknown IDs, an atom that is not present in
its named state, an edge outside a named network, or an edge/reference-basin
mismatch is invalid. The calculation layer delegates the scientific meaning
of states, atom maps, catalyst closure and reference basins to the validated
mechanism-network artifact.

When a stage needs an electronic or coordinate state, the review supplies the
formal charge, multiplicity, and complete ordered list of `{state_id,
atom_id}` references. The builder must not copy a plausible value or treat the
mechanism artifact's lexically sorted atom array as a Gaussian atom order.
Missing charge, multiplicity, or atom order remains a node blocker. A supplied
charge or multiplicity that disagrees with the exact target state, or a
duplicate, missing, foreign, or reordered atom inventory that violates the
reviewed target, is rejected rather than repaired.

Inputs and outputs are typed abstract slots. A node input sourced from another
node must name that producer in `depends_on`; every dependency must exist and
be represented by a consumed source slot. A required input cannot have a null
producer. Output `artifact_role` values are unique within each node, so the
reserved future `{study_id, plan_id, node_id} + artifact_role` adapter locator
is unambiguous. These roles reserve places for future specialist artifacts and
are not file paths, Gaussian route sections, server projects, or job IDs.

## Dependency and stage order

Dependencies form one finite DAG. Self-dependencies, duplicate dependency
IDs, missing nodes, cycles, inconsistent input producers, duplicate slot IDs,
and disconnected orphan work are rejected. The emitted `topological_order` is
the deterministic lexical tie-break order recomputed from the dependency
graph, never review-authored scheduling priority.

Every dependency must also preserve its exact mechanism target: network and
reference-basin sets match, edge-to-edge stages retain the same edge, and the
source and destination share an explicit state or edge endpoint. A compatible
kind and artifact role cannot connect unrelated states, edges, networks, or
reference basins.

The stage ranks are closed and forward-only:

```text
minimum | conformer | complex
  -> ts_candidate
  -> ts_freq
  -> irc_forward | irc_reverse
  -> endpoint
  -> single_point
  -> thermochemistry
  -> sensitivity
```

The exact allowed predecessor matrix is closed: structural nodes may consume
other structural nodes; `ts_candidate` consumes structural nodes; `ts_freq`
consumes `ts_candidate`; each IRC direction consumes `ts_freq`; `endpoint`
consumes an IRC direction; a state-targeted `single_point` consumes only a
`minimum` or `endpoint`, while an edge-targeted `single_point` consumes only
`ts_freq`; `thermochemistry` consumes `minimum`, `ts_freq`, `endpoint`, or
`single_point`; and `sensitivity` consumes `single_point` or
`thermochemistry`. Every non-structural kind requires a predecessor. Every
active node with a non-empty `edge_ids` target directly inherits the
TS-precedent blocker, including edge-targeted single-point, thermochemistry,
and sensitivity nodes. This ordering records dependencies only; it neither
chooses a protocol nor authorizes execution.

## Alternatives and supersession

An alternative group contains at least two nodes and has one policy:

- `retain_all`: all members remain selected;
- `select_one`: exactly one reviewed member is selected;
- `select_zero_or_one`: zero or one reviewed member may be selected.

Selected nodes must be group members, group IDs and memberships must be
unique, and a node's `alternative_group_id` must agree with the group that
contains it. Unselected members must remain `skipped` or `superseded` history;
they cannot continue as active planned work. Alternatives do not weaken
ordinary dependencies and cannot be used to hide an otherwise required
predecessor. Blocked selection remains a blocker; the builder does not choose
among candidates.

A supersession names one superseding node, one or more retained superseded
nodes, and a non-empty rationale. All referenced nodes remain in the artifact.
Self-supersession, duplicate links, cycles in the supersession relation, a
superseded node marked active, or a disposition inconsistent with the link is
invalid. Failed, rejected, inconclusive, cancelled, skipped, and superseded
work therefore stays visible as historical coverage instead of disappearing
from a rebuilt plan. Multi-generation supersession is permitted only as an
acyclic chain whose final replacement remains active. Node supersession is
traversed iteratively. Exact superseded-plan ancestry is limited to 128 plan
artifacts along one validation path, including the current plan; a deeper path
is rejected with a controlled contract error rather than leaking a runtime
recursion failure.

## Separate readiness and evidence axes

For every node the contract keeps these axes independent:

- scientific readiness: `ready`, `blocked`, or `not_applicable`;
- input-review readiness: `ready_for_review`, `blocked`, or `not_applicable`;
- live-approval readiness: only `not_ready` or `not_applicable` in this slice;
- execution state: `not_started`, `succeeded`, `failed`, `cancelled`, or
  `not_applicable`;
- evidence acceptance: `not_available`, `pending_review`, `accepted`,
  `rejected`, `inconclusive`, or `not_applicable`.

Each readiness record lists the exact blocker IDs supporting its status.
Execution completion is not scientific acceptance, and accepted evidence does
not imply input review or live approval. Every node has `executable: false`.
The whole plan always retains:

```yaml
calculation_ready: false
no_submission_authorization: true
```

## Read-only study index

`gaussian-reaction-study-index/1` is a deterministic resume view over one
exact calculation plan and its exact artifact inventory. It contains no
manually editable current-state flag. The index recomputes:

- current, superseded and missing artifact roles;
- ordered stage gates and the last accepted stage;
- the next blockers and one bounded next safe offline action;
- stable node locators and the five independent node-status axes; and
- node-kind and mechanism state/edge/network/reference-basin coverage,
  separated into active and historical node IDs.

The ordered study gates are the W1 intake, species registry and condition
model; the finalized mechanism network; mechanism support bound to that exact
network; the TS-precedent map dependent on the reviewed network/support; and
the calculation plan. The network's support-availability blocker is retained
in plan/node scientific readiness but attributed to the following support gate
for resume progression. A missing or blocked earlier gate cannot be skipped by
a later artifact. `last_accepted_stage` is derived from the contiguous accepted
prefix, and `next_blockers` comes from the first gate that is missing, blocked,
or accepted only with blockers. Every stage blocker ID resolves to the exact
normalized blocker record in the calculation plan, preserving upstream scope
and description; generic fallback blockers are forbidden. `not_reached` does
not mean rejected; it means an earlier gate has not closed.

`node_resume` points back to `{study_id, plan_id, node_id}` and reports where
offline review can safely resume. It does not mutate the node or dispatch a
specialist. Superseded artifacts remain exact bindings in the index. The index
always has `read_only: true`, `calculation_ready: false`, and
`no_submission_authorization: true`.

## Specialist ownership

This orchestration slice preserves existing ownership boundaries:

- reaction-literature owns literature evidence; the origin evidence-gate
  mechanism-support contract remains authoritative for exact edge/channel
  exploration eligibility, while the implemented TS-precedent owner contract
  remains authoritative for its local promotion gate;
- reaction-workflow owns immutable study bookkeeping, dependency validation,
  blockers and the read-only resume view;
- asymmetric-catalysis owns ensemble and stereochemical-channel coverage;
- RTwin/PBS owns protocol presentation, Gaussian input rendering, transport,
  scheduler state and guarded live actions; and
- TS–IRC owns TS/Freq observations, manual mode evidence, separately reviewed
  IRC directions and endpoint/path acceptance.

The installed calculation-DAG entry point loads the exact deployed owner
validators from `auto-g16-knowledge-base` and
`auto-g16-reaction-literature`; its adapter path additionally delegates to
`auto-g16-asymmetric-catalysis`, `auto-g16-rtwin-pbs`, and
`auto-g16-ts-irc`. A deployed-copy smoke must first prove those five named
Skill packages synchronized (or synchronize an explicitly reviewed exact
plan). Deploying only `auto-g16-reaction-workflow` is not a valid smoke setup.

Accordingly, calculation-plan fields cannot contain a Gaussian route,
functional, basis/ECP, solvent-model choice, resources, input text, server
path, job ID, retry instruction, cancellation, or deletion request. Those are
unknown fields here and must fail closed.

## Reviewed external-target mapping and append-only update

The narrow implemented bridge consumes the feature-3
`gaussian-candidate-target-import/1` envelope without importing adapter-owned
identity semantics. `external_target_key` remains only the adapter join key;
it is never parsed, guessed, or reused as a DAG `node_id`.

The human decision is first finalized as the closed, hash-bound
`gaussian-reaction-calculation-target-mapping-review/1` artifact. It contains:

- exact local, non-null references to the target calculation plan and target
  import;
- the exact `external_target_key` and DAG-owned locator
  `{study_id, plan_id, node_id}`;
- `expected_node_kind: ts_candidate`, `update_kind: candidate_inventory`, and
  `artifact_role: candidate_target_import`;
- zero or more exact local prior node-update bindings under `supersedes`; and
- reviewer, reviewed time, decision, notes and the offline safety constants.

Only an accepted mapping can build
`gaussian-reaction-calculation-node-update/1`. The update binds the exact plan,
mapping review, target import and prior updates, and copies only deterministic
target facts selected by the reviewed external key. Version `/1` is
deliberately closed to candidate-inventory attachment on a `ts_candidate`;
generic artifact roles, other node kinds and later update kinds require a
versioned contract extension.

Standalone validation reruns the calculation-plan validator, the adapter owner
validator, exact local reference checks, node-kind/locator checks, target-key
selection and deterministic reconstruction. Adapter references that permit an
absolute path or null payload are not copied into the DAG reference layer.
The mapping review and node update must share one artifact root; node-update
validation revalidates all review bindings relative to the review file itself
and compares them with the update-side resolution, preventing parent/subfolder
root reinterpretation.
Neither artifact mutates the plan or changes any readiness, execution or
evidence-acceptance axis. Supersession is append-only and every review/update
retains `calculation_ready: false` and `no_submission_authorization: true`.
