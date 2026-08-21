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

The current post-V30-4 scientific-validation sequence is:

1. `V30-RESULT-SECTION-ATTRIBUTION-CONTRACT-01`
2. `V30-RESULT-SECTION-ATTRIBUTION-IMPL-01` (separate Owner Gate)
3. resume `V30-MIN-VALIDATE-CONTRACT-01`
4. `V30-VAL-SCI-01` (separate Owner Gate)
5. `V30-MIN-VALIDATE-IMPL-01` (separate Owner Gate)
6. `V30-EXEC-02` (`WAIT`)

The control structure remains serial at integration:

```text
Integration Owner
└── V30-RESULT-SECTION-ATTRIBUTION-CONTRACT-01
    -> V30-RESULT-SECTION-ATTRIBUTION-IMPL-01
    -> V30-MIN-VALIDATE-CONTRACT-01
    -> V30-VAL-SCI-01
    -> V30-MIN-VALIDATE-IMPL-01
V30-EXEC-02 WAIT
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
  the exact artifact/status matrix and diagnostic codes, zero-based half-open
  spans bound to one envelope artifact, strict store/reopen attestation,
  complete ordered frequency and geometry blocks with malformed-block fail
  closure, no cross-source splicing, identity conflict behavior, scientific
  neutrality, and the full offset-asserting adversarial matrix in
  `acceptance.md`.
- **Handoff:** Freeze base/head/tree and exact authority-file scope, reuse
  adjudication, P0-P3 findings, validation evidence, and the independent
  Contract Review. Completion authorizes neither publication nor
  `V30-RESULT-SECTION-ATTRIBUTION-IMPL-01`.

### V30-EXEC-02

- **Outcome:** Deliver the Owner-selected second execution/transport increment
  against the already validated public boundary; its concrete behavior is
  intentionally not guessed here.
- **Scope:** `WAIT`. No breakdown or modification is allowed until the RTwin
  validation evidence and the exact follow-on scope are reviewed.
- **Explicit non-goals:** No implementation, delegation, speculative adapter or
  transport design, live operation, or boundary change while waiting.
- **Dependencies:** A separately authorized RTwin validation of the
  execution/transport public boundary, completion of its review, and explicit
  Owner activation with an exact contract.
- **Autonomy:** `OWNER-GUIDED`; `WAIT`.
- **Stop rules:** Any activity before all dependencies are satisfied is a stop;
  after activation, all `OWNER-GUIDED` and general stop rules apply.
- **Acceptance/validation:** None while `WAIT`. The activation gate must name
  outcome, paths, acceptance, offline evidence, any separately approved live
  evidence, and review owner before work begins.
- **Handoff:** Report `WAIT`, dependency evidence present/missing, blocker, and
  Owner activation as the only next gate.

Contract completion grants no automatic authority to implement Result
attribution, resume or implement ScientificValidation, activate
`V30-VAL-SCI-01`, open `V30-EXEC-02`, or perform live work.
