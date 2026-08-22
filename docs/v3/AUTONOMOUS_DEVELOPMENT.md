# Auto-G16 v3 Autonomous Development

This is the short, executable autonomy contract for post-Core work. It does
not replace [`AGENTS.md`](../../AGENTS.md) or the
[`development handbook`](../development-handbook.md), change a public
contract, or authorize implementation, integration, live work, or deployment.

## Autonomy Contract

| Class | Autonomous breakdown | Modification boundary | Validation, review, and handoff | Stop and request Owner |
| --- | --- | --- | --- | --- |
| `OWNER-GUIDED` | Break the named task into analysis, implementation, and validation checkpoints only; do not create another lane. | Change only owner-approved paths and behavior inside the frozen Task Contract. | Use focused/affected feedback, author findings-first review, then the named Owner or independent gate; hand off each boundary decision. | Before choosing or changing a public contract, schema, invariant, security/live boundary, dependency, or scope; also on any general stop below. |
| `BOUNDED-AUTONOMOUS` | Split independently testable work inside the frozen outcome and scope, subject to the global workstream limit. | Make the smallest coherent changes expressly allowed by the Task Contract; no adjacent cleanup or new framework. | Use focused/affected feedback and author findings-first review; freeze one candidate for independent review and Integration Owner handoff. | When the contract no longer determines a safe choice, a boundary would change, the scope would expand, or any general stop applies. |
| `MAINTENANCE` | Diagnose and apply a minimal behavior-preserving repair within the named maintenance boundary. | Documentation, compatibility, dependency, security, or release hygiene only where intended behavior is already explicit. | Reproduce where applicable, validate the changed and affected surface, self-review, and hand off residual risk. | If intended behavior is unclear, product behavior would change, or a security/live semantic would be weakened or redefined. |

No class grants push, PR, merge, deployment, SSH, RTwin, PBS, Gaussian, live
smoke, retry, cancellation, cleanup, or scientific-acceptance authority.

## Execution and Monitoring Rules

- Stop and request Owner when a required contract is missing or conflicts with
  another contract; do not guess the missing API, schema, field, invariant,
  dependency, test, or acceptance rule.
- Stop before changing a public API, schema, invariant, security boundary, live
  boundary, required check, workflow contract, or branch protection.
- Stop when scope or dependencies must expand, or after two failed repair
  attempts of the same class. Preserve the evidence and report the blocker.
- Maximum parallelism is three workstreams. The Integration Owner alone merges
  or integrates them, serially. Planning does not create a fourth workstream.
- GitHub timestamps ending in `Z` are UTC; convert them to the Owner's local
  time in Owner-facing reports. Report only a state change, anomaly, or terminal
  state. No-change polling is silent.
- `running` is not `failed`. A slow runner or harness that is still running must
  not be failed, rerun, or given an unapproved timeout.
- Focused and affected checks are the default development feedback. Full
  validation is integration/release attestation, not routine per-edit feedback.
  Do not repeat full validation on the same frozen candidate. A legacy-heavy
  full suite is not the default feedback loop for an ordinary v3 PR.
- Every handoff is compact and contains: `task`, `base`, `head`, `scope`,
  `autonomy`, `status`, `findings`, `validation`, `blocker`, and `next gate`.

## Frozen Post-Core Task Contracts

The current post-foundation execution/composition sequence is:

1. freeze and integrate `V30-EXEC-02-COMPOSITION-CONTRACT-01`
2. `V30-VAL-TRANSPORT-01` (separate Owner Gate)
3. V30-EXEC-02 Transport implementation (separate Owner Gate)
4. `V30-A-SYNTHETIC-COMPOSITION-01` test-only integration after Transport main
5. `V30-A-READINESS-01` repeat audit before any live gate

The control structure remains serial at integration:

```text
Integration Owner
└── V30-EXEC-02-COMPOSITION-CONTRACT-01
    -> V30-VAL-TRANSPORT-01
    -> V30-EXEC-02 implementation
    -> V30-A-SYNTHETIC-COMPOSITION-01
    -> V30-A-READINESS-01
Live remains NO-GO
```

At most three independent workstreams may be active concurrently. Integration
and merge remain serial. Historical closed contracts below remain authority
for their owned surfaces.

### V3-MAINT-TEST-01

- **Outcome:** Specify and, only after its later Owner opening gate, build a
  change-aware v3 validation loop that shortens normal feedback without losing
  required safety evidence or required-check compatibility.
- **Scope:** Inventory current tests and check mappings; define changed-path to
  focused/affected selection; propose candidate legacy release/nightly moves;
  map safety semantics to retained or rebuilt v3 evidence; measure the approved
  lanes. The selector owns test selection only, not test meaning or policy.
- **Explicit non-goals:** No implementation during this Planning Gate. Do not
  rename/remove required contexts, edit workflow or branch protection, weaken a
  safety assertion, or make the legacy/release full suite a normal v3 PR gate.
- **Dependencies:** Core is `CLOSED`; OD-08 and the current required-check
  contract remain authoritative; an Owner gate is required before any action
  that changes required checks, workflow, or branch protection.
- **Autonomy:** `BOUNDED-AUTONOMOUS`; high priority. The frozen scope permits
  inventory and proposals. Mutation begins only when the lane is separately
  opened, and boundary changes still stop for Owner.
- **Stop rules:** Fail closed on an unmapped, ambiguous, invalid, or unavailable
  selector input by expanding to the applicable offline full/owner-review gate,
  never by skipping evidence. Stop for unknown test ownership, check-name drift,
  a proposed safety downgrade, scope expansion, or two same-class repair
  failures.
- **Acceptance/validation:** The inventory must identify exact tests before any
  move. Only proven redundant topology replays, release/archive checks, and
  pressure/performance cases are candidates for release/nightly; tests carrying
  real safety meaning are not. No-overwrite, one-submission, uncertainty/no
  automatic retry, reconciliation, owner/approval separation, still-applicable
  capability/descriptor protections, and timeout/slow-running semantics must
  remain or be rebuilt as v3 focused/affected evidence. Stable contexts remain
  `python-compatibility (3.11)`, `python-compatibility (3.12)`,
  `python-compatibility (3.13)`, `source-archive-release`, and
  `chemistry-dependencies`. Engineering targets are focused `<3m`, affected
  `<15m`, and v3 full `<30m`; a legacy/release full run may be slower but does
  not block the ordinary v3 loop. Validate selector mapping, fail-closed cases,
  safety-evidence coverage, exact check expansion, and measured timings offline.
- **Handoff:** Report the exact inventory and proposed moves, retained/rebuilt
  safety map, unchanged or proposed check topology, timings, findings, blockers,
  and the next Owner decision. A proposal is not permission to edit CI.

### V30-EXEC-01

- **Outcome:** Produce the first owner-approved, offline-verifiable v3
  execution/transport slice while preserving the frozen Core boundary and the
  reviewed execution-safety semantics.
- **Scope:** Contract-first definition of the `ExecutionSnapshot`, execution
  safety, and RTwin/OpenSSH public boundary; after explicit Owner approval,
  implement only that approved slice with synthetic offline adapters/fixtures.
- **Explicit non-goals:** No work during this Planning Gate; no live connection,
  submission, deployment, scientific policy, automatic retry, Core contract
  change, or inheritance of the old private owner/capability architecture.
- **Dependencies:** Core `CLOSED`; OD-03 through OD-07; an Owner-approved public
  contract and exact acceptance surface before implementation.
- **Autonomy:** `OWNER-GUIDED`.
- **Stop rules:** Stop on any missing/conflicting public contract, API/schema/
  invariant/security/live-boundary choice, transport-target ambiguity,
  dependency expansion, or two same-class repair failures.
- **Acceptance/validation:** Owner-approved public boundary; new Attempt/no
  overwrite, at-most-one submission, `UNKNOWN` reconciliation, and no automatic
  retry remain explicit; Core remains transport-free. Use focused/affected
  synthetic offline checks and adversarial boundary review. Record all live-only
  gaps without trying to close them.
- **Handoff:** Freeze the approved contract, exact changed paths, offline
  evidence, findings, remaining live-only gap, and Owner/independent next gate.

### V30-RESULT-01

- **Outcome:** Materialize typed, provenance-bearing result observations from a
  frozen program-adapter output boundary without turning parsing into scientific
  acceptance.
- **Scope:** After the input/result boundary is explicitly frozen, implement the
  bounded offline result interpretation and persistence slice against synthetic
  artifacts; use the existing Core types without changing their contract.
- **Explicit non-goals:** No execution or transport, no Gaussian/PBS/RTwin live
  work, no scientific minimum/TS/IRC acceptance, no new schema/framework, and no
  Core public-boundary change.
- **Dependencies:** Core `CLOSED`; owner-frozen adapter input and result
  acceptance contract. Synthetic boundary fixtures keep this lane independent
  from completion of `V30-EXEC-01` until serial integration.
- **Autonomy:** `BOUNDED-AUTONOMOUS` after the dependency contract is frozen.
- **Stop rules:** Stop rather than invent adapter fields, result states,
  provenance, invariants, or scientific meaning; also stop for public-boundary,
  scope, dependency, or security/live changes and two same-class failures.
- **Acceptance/validation:** Focused/affected offline checks cover complete,
  partial, malformed, and conflicting synthetic results, identity/provenance,
  append-only persistence, and the separation between observation and
  scientific acceptance. Independent review is required before integration.
- **Handoff:** Freeze input/output contract identity, scope, findings,
  validation evidence, unresolved scientific decisions, and Integration Owner
  next gate.

### V30-WF-CONTRACT-01

- **Outcome:** Freeze the smallest deterministic, offline-only V30-4 Workflow
  public boundary for finite dependency ordering, bounded static mapping,
  terminal Attempt-state conditions, HumanGate orchestration, append-only
  decisions, and read-only replay.
- **Scope:** Contract authority only in existing v3 documents and context
  routing. The public package is `auto_g16.workflow`; focused tests will belong
  under `tests/v3/workflow/`. The contract fixes the exact public inventory,
  Core relationships, finite-DAG rules, state/persistence ownership,
  deterministic replay, Approval separation, `UNKNOWN` behavior, acceptance,
  reuse adjudication, and non-goals.
- **Explicit non-goals:** No product or selector implementation, Core/API/schema
  change, Approval/Execution/Result change, dynamic scheduler, callback/plugin
  framework, scientific policy, transport, SSH, RTwin/PBS/Gaussian, deployment,
  live work, `V30-EXEC-02`, or V30-4 implementation.
- **Dependencies:** V30-3 and authority hygiene are `CLOSED`; OD-11 and the
  frozen Workflow boundary/acceptance sections are authoritative. Existing
  public Core WorkflowRun/Task/Attempt/CalculationPlan and Approval/Execution/
  Result contracts stay unchanged.
- **Autonomy:** `OWNER-GUIDED`. The contract may be decomposed into narrow reuse
  inspection, authority drafting, offline consistency checks, and independent
  adversarial review only.
- **Stop rules:** Stop for any required Core field/schema/API, public callback,
  dynamic node creation, attempt enumeration, implicit current-plan selection,
  scientific-condition policy, effectful API, new shared framework, scope
  expansion, frozen-contract conflict, or two same-class repair failures.
- **Acceptance/validation:** Prove exact record/API inventory, exact
  definition-scoped local component IDs, deterministic UUIDv5 replay for the
  complete WorkflowDefinition and decision authority records without circular
  component identity computation, a finite combined Edge/Map DAG with lexical
  topological order and Map-aware readiness, explicit Task/plan/Attempt
  closure, bounded Map and closed terminal-state Condition with exact
  Edge/branch agreement and derived complete branch selection, durable
  append-only decisions, exact store
  create/reopen behavior, deterministic reopened projection, disjoint
  HumanGate filters that cannot activate paths, `UNKNOWN` no-retry, zero
  Core/effect behavior, dependency direction, and byte-identical
  Core/Approval/Execution/Result contracts.
- **Handoff:** Freeze base/head/tree and exact document scope, the narrow
  `PORT`/`EXTRACT`/`WRAP`/`REWRITE`/`DROP`/`DEFER` adjudication, findings,
  validation, and the independent Contract Owner Gate. Completion does not
  authorize publication, selector mutation, or implementation.

### V30-RESULT-SECTION-ATTRIBUTION-CONTRACT-01

- **Outcome:** Freeze the minimum additive Result-owned parser and fact schema
  that can distinguish machine-emitted Gaussian job output from
  user-controlled echo and attribute every downstream scientific evidence
  group to exact bytes.
- **Scope:** Contract authority only. Preserve `GaussianLogParser` v1 and
  existing `gaussian-log-facts` history unchanged; add the public
  `GaussianJobParser` tuple, exact-byte single-job grammar, strict attributed
  facts/spans, all recognized generic geometry blocks, parser status matrix,
  durable reopen checks, acceptance matrix, and narrow reuse adjudication.
- **Explicit non-goals:** No Result or ScientificValidation implementation,
  tests, selector mutation, Core/API/schema change, Execution/Approval/Workflow
  change, multi-job selection, checkpoint dependence, scientific minimum/TS/
  IRC decision, transport, SSH, RTwin/PBS/Gaussian, retry, deployment, or live
  work.
- **Dependencies:** `V30-RESULT-01` and V30-4 are integrated. The public
  adversarial replay proving whole-log echo contamination is the root-cause
  evidence. The failed one-section ScientificValidation candidates remain
  immutable evidence and grant no implementation authority.
- **Autonomy:** `OWNER-GUIDED`. Work may include only narrow parser/reuse
  inspection, authority drafting, offline document consistency checks,
  self-review, and the named independent adversarial contract review.
- **Stop rules:** Stop if safe attribution requires a Core change, a change to
  existing Result identity or `GaussianLogParser` v1 semantics, an Execution/
  Approval/Workflow change, a nondeterministic heuristic, external rerun or
  checkpoint authority, product/test/selector edits, scope expansion, or two
  same-class repairs.
- **Acceptance/validation:** Prove exact tuple-dispatched outer schema-v1
  compatibility, unchanged historical reopen, the normative raw-byte
  LF/CRLF tokenizer, literal/closed-regex FSM transitions and echo suppression,
  the exact artifact/status matrix, one-primary-diagnostic fail-fast ownership,
  disjoint orphan/block/row/numeric/EOF precedence, zero-based half-open spans
  bound to one envelope artifact, strict store/reopen attestation,
  thermochemistry structure/key/numeric/finite validation before a
  prior-committed same-key duplicate check and the full-current-line duplicate
  span,
  complete ordered frequency and geometry blocks with malformed-block fail
  closure, no cross-source splicing, identity conflict behavior, scientific
  neutrality, and the full offset-asserting adversarial matrix in
  `acceptance.md`.
- **Handoff:** Freeze base/head/tree and exact authority-file scope, reuse
  adjudication, P0-P3 findings, validation evidence, and the independent
  Contract Review. Completion authorizes neither publication nor
  `V30-RESULT-SECTION-ATTRIBUTION-IMPL-01`.

### V30-MIN-VALIDATE-CONTRACT-01

- **Outcome:** Freeze the smallest post-Result boundary that classifies one
  exact attributed Gaussian job as `VALIDATED_MINIMUM`, `NOT_MINIMUM`,
  `INCOMPLETE`, or `UNSUPPORTED`, plus a separate immutable human
  `ScientificAcceptance` for an exact validated outcome.
- **Scope:** Authority documents and future context routing only. The future
  public owner is `auto_g16.scientific_validation`, with focused tests under
  `tests/v3/scientific_validation/`. It consumes only persisted Result-owned
  `gaussian-job-facts` and binds one exact plan revision, Attempt,
  InputBinding, complete envelope, ParseOutcome, and validation-policy version.
- **Explicit non-goals:** No product/tests/selector implementation; no raw-log
  access, Gaussian grammar, missing-fact reconstruction, Core/Result/Approval/
  Execution/Workflow change, TS/IRC/connectivity, conformer, qRRHO, scientific
  policy framework, Observe, ReviewBundle, Transport, SSH/RTwin/PBS/Gaussian,
  deployment, or live work. `V30-EXEC-02` remained `WAIT` during this completed
  scientific-validation freeze; OD-17 now separately activates only its
  offline composition contract.
- **Dependencies:** Result attribution contract and implementation are closed;
  `GaussianJobParser` / `gaussian-job-facts` is active. Historical failed
  one-section candidates are negative evidence only. Public Result facts and
  their exact source spans are the sole Gaussian evidence authority.
- **Autonomy:** `OWNER-GUIDED`. This lane may inspect current public Result
  facts, draft only the six approved authority files, run lightweight document
  and context checks, and freeze one candidate for independent review.
- **Stop rules:** Stop if any decision needs raw Gaussian bytes, a new Result
  fact/span or semantic change, a Core/API/schema change, upstream contract
  reopening, selector/product/test edits, a nondeterministic heuristic, scope
  expansion, or live authority.
- **Acceptance/validation:** Prove the exact parser tuple and provenance chain;
  equal ordered optimization/stationary evidence pairing; rightmost eligible
  geometry before the final accepted optimization marker; the complete ordered
  frequency-block suffix after its stationary marker; no cross-source splice;
  nonlinear `3*N-6` support; zero negative-frequency tolerance; the exact four
  outcomes; append-only deterministic identities/store replay; acceptance only
  for exact `VALIDATED_MINIMUM`; and all eighteen mandatory adversarial cases
  in `acceptance.md` without raw-output interpretation.
- **Handoff:** Report exact base/head/tree/six-file scope, `PORT`/`DROP`/`DEFER`
  disposition, P0-P3 findings, validation, remaining ambiguity, and the
  independent Contract Review. Completion authorizes neither publication,
  `V30-VAL-SCI-01`, implementation, nor live work.

### V30-EXEC-02

- **Outcome:** Freeze the RTwin-first V30-A composition boundary without product
  implementation. The Controller performs pure approval replay, never
  pre-claims, and invokes the unchanged `execute_once(...)`; that single
  Execution entrypoint owns the Core claim and permits only `WINNER` to cross
  the first effect seam. Freeze read-only scheduler evidence, exact output
  fetch, Observe mapping, Result-owned envelope/parser boundaries, and one full
  synthetic composition test.
- **Scope:** Authority files only:
  `OWNER_DECISIONS.md`, `docs/v3/boundary-spec.md`,
  `docs/v3/acceptance.md`, `docs/v3/AUTONOMOUS_DEVELOPMENT.md`,
  `docs/v3/STATUS.md`, and `config/context-map.toml`. Use the minimum subset;
  a seventh path is forbidden. No product, test, selector, workflow, or live
  mutation is part of this contract freeze.
- **Explicit non-goals:** No existing Core/Approval/Workflow/Execution/Observe/
  Result/ScientificValidation/Review API or schema change; no product
  Controller; no OpenSSH; no process/Gaussian-phase acquisition; no qdel,
  cancellation, cleanup, deployment, credentials, live RTwin/PBS/Gaussian, or
  V30-A run.
- **Dependencies:** Integrated Core, Approval, Workflow, Execution, Observe,
  Result, ScientificValidation, and Review public surfaces plus OD-17. The
  legacy RTwin path remains a WRAP/reuse source rather than v3 authority.
- **Autonomy:** `OWNER-GUIDED`; composition contract freeze is active. Transport
  implementation remains `NO-GO` until this contract and the separate
  `V30-VAL-TRANSPORT-01` ownership gate are integrated.
- **Stop rules:** Stop for a seventh path, upstream public/schema change,
  alternate WINNER owner, distributed-transaction claim, retry from UNKNOWN,
  unclosed transport type/identity/fetch semantics, selector/product mutation,
  OpenSSH or live requirement, or any new scientific policy.
- **Acceptance/validation:** Prove every numbered condition in
  `acceptance.md#v30-exec-02-composition-contract-01-rtwin-first-v30-a-composition`,
  exact context routing, docs/anchors/TOML consistency, complete narrow reuse
  disposition, and independent adversarial contract review with
  `P0/P1/P2/P3 = 0/0/0/0`.
- **Handoff:** Report exact base/head/tree/scope, reuse disposition, validation,
  P0-P3, blockers, and the independent Contract Review. Completion authorizes
  neither publication, `V30-VAL-TRANSPORT-01`, product implementation, nor live
  work.

Contract completion grants no automatic authority to activate
`V30-VAL-TRANSPORT-01`, implement Transport or a Controller, open OpenSSH, or
perform live work.
