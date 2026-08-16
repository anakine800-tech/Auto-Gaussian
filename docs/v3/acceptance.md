# Auto-G16 v3 Acceptance Cases

These are feature-expansion stop conditions, not authority for a live run.

## V30-CORE-01: Clean Runtime Core

**Status: SATISFIED.** Final Core Review is PASS and `V30-CORE-01 = COMPLETE`.

The Core Interface Review milestone is **PASS WITH CONDITIONS**. The
`auto_g16.core` public path, the ten immutable keyword-only domain records, and
their field-level interface are approved. Canonical payload encoding is a
private implementation detail, not a public symbol, constructor annotation,
runtime payload value, or compatibility promise. Public payload fields expose
only a deeply immutable semantic mapping view. `ExecutionSnapshot` remains
excluded.

The following satisfied conditions remain the frozen V30-CORE-01 acceptance
contract for Python 3.11 or newer:

1. A dependency-free `SQLiteRuntimeStore` persists and reloads all ten Core
   record types. It uses SQLite foreign keys, a versioned fresh-database schema,
   explicit transactions, and no implicit migration of an unknown schema. On
   reopening schema version 1, Core verifies the exact owned schema identity,
   including columns, primary and foreign keys, uniqueness, checks, and indexes;
   same-named counterfeit tables fail closed.
2. Immutable record insertion is replay-safe: an exact repeat is idempotent,
   while the same record identity with different content fails closed without
   overwriting the stored value.
3. Every stored `Attempt` starts in `PLANNED`. Its only states are `PLANNED`,
   `SUBMISSION_INTENT_RECORDED`, `SUBMITTED`, `UNKNOWN`, `RUNNING`, `SUCCEEDED`,
   `FAILED`, and `NOT_SUBMITTED`. State changes outside the documented store
   operations fail closed and leave the transaction unchanged.
4. `record_submission_intent` atomically records exactly one caller-supplied
   intent identity and moves `PLANNED -> SUBMISSION_INTENT_RECORDED`. Exactly
   one concurrent caller receives the explicit `WINNER` claim signal that may
   gate an external submission; exact replay receives the distinct `REPLAY`
   signal and cannot be mistaken for that gate. Implicit truth-value use fails
   closed, requiring an explicit `WINNER` comparison. Reusing an intent identity
   for another Attempt, or a different identity for the same Attempt, is a
   conflict. Core never invokes submission itself.
5. `record_submission_outcome` binds the recorded intent to exactly one
   `SUBMITTED` or `UNKNOWN` outcome. Exact replay is idempotent; conflicting
   outcomes fail. `UNKNOWN` never authorizes retry.
6. Reconciliation of `UNKNOWN` requires a persisted `Observation` for the same
   Attempt. `UNRESOLVED` preserves `UNKNOWN`; terminal evidence may resolve it
   once to `SUBMITTED` or `NOT_SUBMITTED`. Direct or conflicting reconciliation
   fails closed.
7. Normal execution progress permits only `SUBMITTED -> RUNNING`,
   `SUBMITTED -> SUCCEEDED|FAILED`, and `RUNNING -> SUCCEEDED|FAILED`.
   `SUCCEEDED`, `FAILED`, and `NOT_SUBMITTED` are terminal in this slice.
8. Each Task has exactly one persisted root `Attempt`; a second parentless
   Attempt fails closed regardless of the root state. A child `Attempt` is
   created only by an explicit call after its parent is `FAILED` or
   `NOT_SUBMITTED`. It preserves the same `task_id`, records the parent identity,
   has a strictly greater positive ordinal, and is a new `PLANNED` Attempt.
   Core never creates a child automatically, and an `UNKNOWN` parent cannot
   have one or be bypassed by another root.
9. `Observation` and `Result` records are append-only, require an existing
   Attempt, survive close/reopen, retain deterministic insertion order, and
   use the same exact-replay/conflicting-identity rule. Their payload storage
   encoding remains private.
10. Public Core has no Transport, PBS, Gaussian, deployment, scheduler query,
    retry executor, cleanup, or `ExecutionSnapshot` behavior. Focused and
    adversarial tests under `tests/v3/core/` include real concurrent intent
    claim, UNKNOWN root-bypass, counterfeit-schema, and private-encoding
    counterexamples. Syntax compilation, static source checks, and
    `git diff --check` pass offline.

All conditions are satisfied. V30-CORE-01 stops at this boundary; completion
does not authorize another v3 slice.

## V30-EXEC-01: Execution Boundary

**Status: CONTRACT FROZEN; IMPLEMENTATION NOT AUTHORIZED.** A future
implementation conforms only when focused, adversarial, synthetic, offline
evidence demonstrates all of the following without SSH, RTwin, PBS, Gaussian,
deployment, or another live effect:

1. Exact replay of identical reviewed Core joins, prepared bytes, resources,
   resolved target, template bytes, workspaces, and program selection produces
   identical Core intent and ExecutionSnapshot identities. Mutation of any
   effect-relevant profile, SSH/runtime configuration, endpoint, or PBS
   template content changes the relevant identity and cannot alter an existing
   snapshot.
2. The complete `Attempt -> Task -> WorkflowRun -> Project` traversal and exact
   `CalculationPlan`/`ResourceSpec` task joins are enforced. Execution consumes
   the Preparation Owner's same sealed bytes and exact resolved resource request
   without rereading ambient input, interpreting the plan, defaulting, or
   resizing.
3. Local, Windows, and server paths satisfy the frozen absolute canonical
   grammar and containment rules. Workspace derivation is deterministic;
   exclusive component-wise no-follow allocation rejects an existing target,
   symlink/reparse point, replacement, escape, endpoint drift, or overwrite,
   while retaining durable evidence for any partial per-platform allocation.
4. PBS template identity derives from the validated immutable raw bytes, exact
   size, and SHA-256. Execution consumes those same bytes; a caller path,
   revision, opaque identity, missing byte value, or mutable reread fails.
5. Concurrent and replay tests prove that only the explicit Core `WINNER`
   enters the effect boundary, at most one submission call occurs for the
   Attempt, and `REPLAY` performs zero adapter, transport, allocation, transfer,
   or submission calls.
6. A proven failure before Core intent/effect remains pre-effect and is not
   classified as submission uncertainty. The frozen legal Core handling of a
   proven no-effect stop after `WINNER` reconciles the same Attempt to
   `NOT_SUBMITTED` without retry.
7. Any possibly effectful ambiguity persists `UNKNOWN` plus exact
   Attempt/snapshot/intent-bound evidence. Missing, multiple, unbound,
   contradictory, or unreliable job evidence remains unresolved.
8. Reconciliation is durable and same-Attempt only. `UNKNOWN` never permits an
   automatic retry, another `qsub`, alternate profile/workspace, bypass
   Attempt, cleanup, cancellation, or `qdel`.
9. Minimal append-only RemoteEffectReceipts persist confirmed and ambiguous
   allocations, transfers, and submission evidence, including partial
   allocation. They are idempotent evidence rather than authority and do not
   grow into an owner-chain, capability, signature, or hash-lineage framework.
10. The synthetic boundary exercises the RTwin-first contract only. It proves
    that ExecutionSnapshot, immutable byte handoffs, receipts, transport, and
    program selection remain outside Core and grants no implementation or live
    authorization.

## V30-RESULT-01: Result Provenance Boundary

**Status: CONTRACT FROZEN; IMPLEMENTATION NOT AUTHORIZED.** A future
implementation conforms only when focused, adversarial, synthetic, offline
evidence demonstrates all of the following:

1. The reader resolves the Core ownership chain and exact CalculationPlan, then
   persists one deterministic input-binding Observation for the Attempt's exact
   SHA-256/size/media-type input. Conflicting plan/input binding fails closed.
2. A valid complete capture persists an exact deterministic envelope and can
   materialize a complete Result only when its named result contract has every
   required fact. Program failure may still be completely captured and parsed.
3. A partial capture stays partial. It may produce only an explicitly partial
   Result with nonempty unambiguous facts and missing codes; no default,
   promotion, or inferred completion is allowed.
4. Malformed envelope metadata, identity, relationship, or artifact validation
   produces no valid envelope or Result and does not alter earlier records.
5. Valid captured bytes that are unparseable or unsupported retain their valid
   envelope and expose `output-sealed/result-absent`; they are not recast as a
   malformed envelope, execution failure, or scientific rejection.
6. New captures and parser name/version/contract/kind combinations produce new
   UUIDv5 identities. Readers enumerate and revalidate all versions, select the
   current capture by frozen Core order, group Results by exact envelope/parser
   identity, and never splice provenance across captures.
7. Exact replay is idempotent with the same identity and original timestamps;
   the same identity with different payload conflicts. New capture/parser
   records append without overwriting history.
8. Observation and Result persistence is append-only across close/reopen and
   retains deterministic Core order. Conflicting or malformed later material
   leaves all prior facts unchanged.
9. `input-bound/output-absent`, `output-sealed/result-absent`, partial Result,
   and complete Result prefixes are durable legal states. A missing later
   record is explicitly incomplete, not failure and not permission to
   synthesize or roll back records.
10. Result creation and reading never mutate or reconcile Attempt state, infer
    execution success/failure, or authorize retry. Program status, capture
    completeness, parse status, Result existence, and scientific acceptance
    remain separate; minimum, TS, IRC, and workflow acceptance are unexecuted
    until their own review.

## v3.0: Closed-Shell Minimum

A real closed-shell minimum completes:

`structure -> plan -> submit -> observe -> fetch -> parse -> ReviewBundle`

When this case meets its reviewed acceptance criteria, stop v3.0 feature
expansion.

## v3.1: Flexible-Molecule Ensemble

A real flexible molecule completes:

`xTB preopt -> CREST -> audit -> DFT -> Freq -> qRRHO -> ensemble`

When this case meets its reviewed acceptance criteria, stop v3.1 feature
expansion.

## v3.2a: Representative Reaction

A representative reaction completes:

`ReactionPlan -> TS search -> mode review -> bidirectional IRC -> endpoints -> barrier`

When this case meets its reviewed acceptance criteria, stop v3.2a feature
expansion.
