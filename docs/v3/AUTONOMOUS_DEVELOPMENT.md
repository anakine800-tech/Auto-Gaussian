# Auto-G16 v3 Autonomous Development

This page separates current general autonomy rules from frozen Task Contracts
and links historical planning/launch records. It does
not replace [`AGENTS.md`](../../AGENTS.md) or the
[`development handbook`](../development-handbook.md), change a public
contract, or authorize implementation, integration, live work, or deployment.

## Autonomy Contract

| Class | Autonomous breakdown | Modification boundary | Validation, review, and handoff | Stop and request Owner |
| --- | --- | --- | --- | --- |
| `OWNER-GUIDED` | Break the named task into analysis, implementation, and validation checkpoints only; do not create another lane. | Change only owner-approved paths and behavior inside the frozen Task Contract. | Use focused/affected feedback, author findings-first review, then the named Owner or independent gate; hand off each boundary decision. | When a public contract, schema, invariant, security/live boundary, dependency or scope decision is missing or would differ from the approved Task Contract; also on any general stop below. |
| `BOUNDED-AUTONOMOUS` | Split independently testable work inside the frozen outcome and scope, subject to the global workstream limit. | Make the smallest coherent changes expressly allowed by the Task Contract; no adjacent cleanup or new framework. | Use focused/affected feedback and author findings-first review; freeze one candidate for independent review and Integration Owner handoff. | When the contract no longer determines a safe choice, a boundary would change, the scope would expand, or any general stop applies. |
| `MAINTENANCE` | Diagnose and apply a minimal behavior-preserving repair within the named maintenance boundary. | Documentation, compatibility, dependency, security, or release hygiene only where intended behavior is already explicit. | Reproduce where applicable, validate the changed and affected surface, self-review, and hand off residual risk. | If intended behavior is unclear, product behavior would change, or a security/live semantic would be weakened or redefined. |

An autonomy class alone grants no push, PR, merge or operational authority.
The Owner may authorize several development steps once for the same bounded
task under [Development authorization](../development-handbook.md#development-authorization).
Continue those steps after their prerequisites pass without repeated permission
requests. Deployment, SSH, RTwin, PBS, Gaussian, live smoke, retry, cancellation,
cleanup and scientific acceptance retain their separate exact gates.

## Execution and Monitoring Rules

- Stop and request Owner when a required contract is missing or conflicts with
  another contract; do not guess the missing API, schema, field, invariant,
  dependency, test, or acceptance rule.
- Stop before an unapproved change to a public API, schema, invariant, security
  or live boundary, required check, workflow contract, or branch protection.
  An explicitly approved change still follows its named contract freeze,
  independent review and implementation gates; do not ask for the same
  decision again or infer that a planning gate authorizes implementation.
- Stop when scope or dependencies must expand. For an ordinary offline repair,
  use the [bounded diagnostic budget](#ordinary-offline-repair-budget) instead
  of the former general two-failure threshold. Preserve stricter task-specific
  stops and all scientific, live, BUS and uncertainty boundaries.
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

### Ordinary offline repair budget

For new ordinary offline repairs whose intended behavior is already defined
by the approved task contract, record a default budget of **four repair cycles
or 30 minutes of active diagnosis/editing, whichever is reached first**.
A cycle states one hypothesis,
makes its bounded repair and runs the relevant check; record the evidence and
remaining budget. Stop further diagnosis/editing at the active-time limit and
do not start another cycle after the recorded count is exhausted if the
problem remains unresolved. An Owner may explicitly set a different finite
budget at intake or approve an extension after reviewing the evidence.

Waiting for an already-running test, CI, or Owner reply does not consume active
diagnosis time. This is not a test timeout: let a running check finish under
its existing policy, and reuse its result. Successful repair proceeds to the
required validation/review; required checks are not skipped to fit the budget.
Do not repeat a failed approach without new evidence or a changed hypothesis.
Missing authority, contract conflict, identity drift or scope expansion stops
immediately, even with budget remaining.

Count across the task's related failures, turns and handoffs; record consumed
cycles/time rather than resetting them for a new error label or process.
Exhaustion requires an Owner decision before further repair. This replaces
only the general two-failure rule for these new tasks: explicit two-failure
stops in frozen Task Contracts remain until separately superseded. It grants
no automatic BUS restart/FIX, remote-operation retry, additional submission
or scientific-method change. Real `UNKNOWN` remains reconciliation-only with
no automatic retry; no diagnostic budget can reopen a consumed Attempt.

## Frozen Post-Core Task Contracts

Read the sections below as frozen, surface-specific contracts, not a current
execution queue. Closing a task does not retire its technical invariants,
compatibility requirements, validation obligations or review thresholds.
Opening gates, exact historical bases, temporary scope and then-current next
steps record their original tasks; they do not authorize a new task or resume
a completed one. Use [STATUS](STATUS.md) for verified integration evidence and
the current explicit Owner Gate for any new action.

| Material | Role and entry |
| --- | --- |
| General autonomy, stop, monitoring and handoff rules | [Autonomy Contract](#autonomy-contract) and [Execution and Monitoring Rules](#execution-and-monitoring-rules), with the [handbook](../development-handbook.md) operation order. |
| Frozen technical Task Contracts | The named sections below and their higher-priority Owner/boundary/acceptance sources; existing anchors are retained. |
| Former “current” post-foundation sequence | [Unchanged planning snapshot](post-core-history.md#post-foundation-sequence-snapshot); no longer the current work queue. |
| Night instruction with a 2026-09-11 deadline | [Original scope, window and invariants](post-core-history.md#v31-night-offline-closeout-20260911); later integration is recorded in STATUS. |
| Superseded selector error clause | [V3-MAINT-TEST-01 entry](#v3-maint-test-01) explicitly routes to its reviewed successor; unaffected requirements remain. |
| C2/C3/C4 proposal and recovery checkpoints | Their original contract text remains below; [current integration evidence](STATUS.md#verified-integration-evidence) separates those checkpoints from later #173–#175 integration. |

### V31-NIGHT-OFFLINE-CLOSEOUT-20260911

Historical launch record: the exact 2026-09-11 instruction, base, deadline and
finite backlog are preserved in [post-Core history](post-core-history.md#v31-night-offline-closeout-20260911).
This anchor remains the compatibility entry used by boundary, acceptance and
context routing. The retained A/C/D invariants and scope/validation/safety
limits still describe the delivered private surfaces; they are not repealed
by relocation. The launch window does not recur. The collection was later
integrated through [PR #168](STATUS.md#verified-integration-evidence), under
separate integration authority. Neither record grants new live authority.

### V31-CHANGE-AWARE-VALIDATION-NO-ACCIDENTAL-FULL-01

The selector error-stop contract below is the reviewed successor to the old
expand-on-error clause in [V3-MAINT-TEST-01](#v3-maint-test-01), consistent with
[OD-08](../../OWNER_DECISIONS.md#od-08-runtime-and-change-aware-ci) and
[handbook section 6](../development-handbook.md#6-validation-ladder-and-deduplication).
Its branch-opening and publication steps are historical task instructions,
not a new authorization. This annotation changes no selector semantics.

- **Owner opening gate:** Continue the xTB runtime-data authority branch from
  `7a624e8db9f5adcf9436a5abc88145ddd68089bd`; do not publish that parent alone.
- **Class/scope:** Feature development, L2 CI/compatibility review. Repair
  selector/runner/CI, modern route ownership, discovery completeness and
  duplicate collection, bounded adversarial tests, and operator documentation.
  This successor replaces the older expand-on-error selector behavior below.
- **Contract:** Every Git-tracked `auto_g16/`, `tests/v3/`, and `tests/v31/`
  path has exactly one reviewed route. Unknown modern ownership emits
  `UNMAPPED_MODERN_PATH`, fails fast, and starts zero tests, even alongside
  selector self-protection changes. Existing V31 Transport prefixes have an
  explicit affected owner. An invalid/non-authoritative selector cannot start
  any CI test suite. Bare local `run_tests.py` refuses implicit full discovery.
- **Full ownership:** The 3.11/3.12/3.13 matrix always runs bounded selected
  evidence. Only authoritative `legacy-release` permits the source archive to
  run complete discovery with pressure coverage; it is the one CI full owner.
  Preserve the five required contexts. Unbound manual/release-like events
  fail fast and cannot request full attestation implicitly.
- **Freeze/validation:** Use focused, adversarial, affected and bounded v3
  checks before one complete local full on the final frozen HEAD. Preserve
  its command, HEAD/tree, terminal counts, duration and modifiers externally;
  do not repeat full on unchanged HEAD/tree. Only after success, push/create
  the combined PR, prove exactly one remote full owner, and hand off review.
- **Non-goals:** No xTB installation, CREST installation, ServerProfile/live
  qualification, remote chemistry, Skill deployment, or branch-protection
  changes. Review and merge remain separate from production installation.

### V3-MAINT-TEST-01

**Partial supersession:** only the historical selector expand-on-error clause
quoted below is replaced by
[V31-CHANGE-AWARE-VALIDATION-NO-ACCIDENTAL-FULL-01](#v31-change-aware-validation-no-accidental-full-01).
Unknown modern ownership and invalid/non-authoritative selector inputs stop
before tests; an error is not permission for full discovery. Reviewed
conservative routes retain their existing required validation. All unaffected
scope, safety, review and stop requirements below remain binding.

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
- **Historical selector clause (superseded; do not execute):**

  > Fail closed on an unmapped, ambiguous, invalid, or unavailable
  > selector input by expanding to the applicable offline full/owner-review gate,
  > never by skipping evidence.
- **Retained stop rules:** Stop for unknown test ownership, check-name drift,
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

### V30-A-GAUSSIAN-OPTFREQ-COMPOSITE-JOB-RESULT-CONTRACT-PARSER-REPAIR-01

- **Outcome:** Add parser `1.1.0` / grammar-2 support for one external Gaussian
  invocation with a closed contiguous internal-step chain, then let existing
  ScientificValidation consume the unchanged attributed fact shape.
- **Scope:** `auto_g16.result` parser/model tuple dispatch,
  `auto_g16.scientific_validation` tuple-aware terminal and evidence
  selection, focused/affected offline tests, the named authority documents,
  exact immutable-capture qualification, independent review, PR, CI, merge,
  and exact-main zero-network replay.
- **Compatibility:** `1.0.0` / grammar-1 remains readable and keeps its exact
  semantics. The new tuple changes Result identity naturally; no old Result,
  envelope, input binding, or public schema is mutated.
- **Autonomy:** `OWNER-GUIDED`, with implementation, normal PR, and merge
  explicitly authorized by the current Owner Gate after zero findings and
  green required checks.
- **Stop rules:** Stop for a second external job, `--Link1--` workflow,
  non-contiguous or ambiguous internal steps, schema/API/reason-vocabulary
  change, raw-byte interpretation in ScientificValidation, artifact-specific
  special casing, an exact-capture parse failure after the narrow repair, or
  any network/live/deployment/effect requirement.
- **Acceptance:** Prove the complete negative and positive grammar matrix,
  legacy reopen, exact two-terminal capture facts, unchanged minimum policy,
  exact three-mode positive frequencies, three-atom selected geometry,
  deterministic append-only identities, and zero product effects.
- **Handoff:** After merge, preserve old and new ParseOutcomes, select the new
  current Result, terminalize Core only through its public lifecycle if the
  composite is all-normal, record minimum validation and an eligible but
  unaccepted ReviewBundle, and return for Owner scientific acceptance.

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
- **Autonomy:** `OWNER-GUIDED`; composition contract and
  `V30-VAL-TRANSPORT-01` are integrated. Transport implementation remains
  `NO-GO` until `V30-TRANSPORT-BOOTSTRAP-CHAIN-03` is integrated.
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
  P0-P3, blockers, and the independent Contract Review. Its completed
  integration authorized neither product implementation nor live work;
  `V30-VAL-TRANSPORT-01` was activated and integrated by its later separate
  gate.

Contract completion grants no automatic authority to implement a product
Controller, open OpenSSH, or perform live work.

### V30-TRANSPORT-BOOTSTRAP-CHAIN-03

- **Outcome:** Close the implementation-review findings with one Transport-
  owned append-only SQLite `TransportStore`, durable remote workspace/artifact/
  job/receipt physical bindings, an explicit preinstalled bootstrap trust root,
  replacement-safe descriptor-relative remote operations, and deployment-
  manifest-bound executable invocation within the exact frozen threat model.
- **Scope:** Exact authority files only: `OWNER_DECISIONS.md`,
  `docs/v3/boundary-spec.md`, `docs/v3/acceptance.md`,
  `docs/v3/AUTONOMOUS_DEVELOPMENT.md`, and `docs/v3/STATUS.md`. No context-map,
  selector, product, or test mutation.
- **Failed evidence:** `798d3559d7c5ee6211a0b29977310f8adb871a5f`,
  `e49136e23c564cc9e0d9d97b905e43c45db73adc`, and
  `44db04180af8222c6e4619accfab0049e89bd3e0` remain immutable negative
  evidence; the last lacked closed per-operation response/binding schemas and
  one realizable fetch response channel.
- **Public shape:** Add only `TransportStore.create_new(path, *, approved_root)`,
  `TransportStore.open_existing(path, *, approved_root)`, and `close()`; add
  exact `transport_store_id` and `store_instance_id` bindings to Transport
  evidence; and require the same store in both RTwin adapter constructors and
  persisted job-binding replay. The effect adapter additionally receives the
  current public `ServerProfile` so manifest bytes have exactly one source and
  can close against each snapshot. Existing public Core/Approval/Workflow/
  Execution/Observe/Result/ScientificValidation/Review APIs and schemas remain
  unchanged.
- **Persistence:** Exact schema-v1 append-only store, deterministic UUIDv5
  identities, a one-time non-caller-selectable OS-CSPRNG nonce, exact logical
  store and physical-instance binding, idempotent replay, conflict fail-closed,
  descriptor-relative/no-follow root-parent-terminal handling, durable reopen,
  and no effect/retry/scientific authority. It detects clone/replacement within
  the frozen model; it does not claim uncloneability against malicious same-UID,
  root, kernel/filesystem, or deployment/bootstrap compromise.
- **Trust:** The exact canonical runtime content
  `transport-deployment-manifest-v1.json`, closed against the current resolved
  profile and snapshot, is final pre-start authority inside the frozen model.
  Its exact nine roots include both configured remote shells. `server_python`
  does not establish that trust; after deployment-trusted start it may detect
  drift and process only the fixed bootstrap source plus closed data packets.
  Caller source/module/operation upload, `eval`, `exec`, and arbitrary command
  execution are forbidden.
- **Safety:** Persist and reattest opaque workspace and artifact physical tokens
  descriptor-relatively/no-follow for every later effect/read. Freeze exact
  deployment-manifest evidence for every used executable, exact absolute-path
  structured execution, Windows first-hop parser/quoting, and POSIX single-token
  quoting when unavoidable. Descriptor execution and a new native wrapper are
  not required; strict prelaunch and practical postlaunch reattestation do not
  overclaim TOCTOU protection against excluded actors. Channels stay bounded
  through completion and EOF. Every operation uses one exact AGV3 request frame
  on stdin and one exact AGV3 response frame on stdout with an operation-specific
  closed binding/payload/result schema; stderr is capped diagnostic-only, and
  no unspecified binary/authority channel exists.
- **Command chain:** Freeze the real Mac OpenSSH -> Windows OpenSSH server ->
  declared `powershell-v1` or `cmd-v1` remote shell -> RTwin OpenSSH -> server
  OpenSSH -> `posix-sh-v1` -> `server_python` chain. Local `shell=False` removes
  only a local shell. `powershell-v1` has the exact file-attestation launcher;
  `cmd-v1` has exact quoting but fails deployment compatibility under this
  nine-root model because it has no trusted SHA-256 primitive. No grammar
  detection or fallback is permitted.
- **Reuse:** PORT/EXTRACT reviewed append-only SQLite, lexical no-follow,
  manifest, quoting, and stable-channel primitives; WRAP proven RTwin operation
  mechanics; REWRITE only store/physical-binding/data-protocol glue that legacy
  code couples to v2 governance or dynamic command behavior; DROP v2 authority,
  implicit retry/cleanup, self-attestation, and dynamic agent execution; DEFER
  a native wrapper, OpenSSH, deployment, credentials, and live work.
- **Explicit non-goals:** No Core/Execution store/API change, no alternate
  WINNER owner, no OpenSSH, deployment, credential/host-key policy, retry,
  qdel, deletion, cleanup, live RTwin/PBS/Gaussian, or V30-A live run.
- **Autonomy:** `OWNER-GUIDED` docs-only closeout. Once exact authority content
  is integrated after independent `0/0/0/0` review, the successor offline
  Transport implementation is gate-eligible; this document alone does not
  perform or authorize product/live mutation.
- **Acceptance:** Prove all conditions in
  `acceptance.md#v30-transport-bootstrap-chain-03-deployment-manifest-and-closed-command-chain`,
  exact five-file scope, docs/anchor/static/diff/sensitive checks, and
  independent adversarial contract review.
- **Stop rules:** Stop for any existing upstream API/schema change, alternate
  trust root, dynamic remote code requirement, inability to persist/replay
  physical authority without retry, deployment/live requirement, sixth file,
  or unresolved P0/P1.

### `V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01`

- **Outcome:** Close the gap between snapshot-bound scheduler resources and the
  actual qsub invocation through one closed, deterministic, source-controlled
  dialect renderer.
- **Authority:** `OWNER-GUIDED`, followed by bounded autonomous implementation
  only after fresh independent contract review reaches `0/0/0/0`.
- **Contract scope:** `OWNER_DECISIONS.md`, `docs/v3/boundary-spec.md`,
  `docs/v3/acceptance.md`, this file, `docs/v3/STATUS.md`, and
  `config/context-map.toml` only.
- **Implementation scope:** Transport-owned bootstrap/driver/adapter code and
  `tests/v3/transport/**` only. No upstream public API/schema change.
- **Source authority:** Exact snapshot `ResolvedResourceRequest`; neither PBS
  bytes, Gaussian `%mem`/`%nprocshared`, caller argv, environment, profile
  defaults, scheduler defaults, nor legacy governance may replace it.
- **Dialect:** Fixed runtime content `pbs-resource-enactment-v1.json` selects a
  closed source renderer. The separate `V30-PBS-TORQUE-DIALECT-01` authority
  records the accepted read-only deployment evidence and exact production
  renderer. One explicitly synthetic renderer remains allowed offline and must
  be rejected before any live subprocess starts.
- **Protocol:** Successor bootstrap `/2`, table `/2`, and bootstrap-v2 source;
  same seven operations, framing, trust roots, caps, physical bindings,
  WINNER/REPLAY/UNKNOWN, and no-retry rules.
- **Validation:** Focused Transport, exact resource/dialect/request vectors,
  affected selector evidence once, synthetic composition deltas, and fresh
  independent adversarial review.
- **Reuse:** PORT resource/validation/no-shell primitives; EXTRACT neutral
  historical deployment facts only; WRAP RTwin/PBS mechanics; REWRITE the
  enactment seam because v3 currently omits resources and v2 governance is not
  authority; DROP caller/free-form/default and v2 authority; DEFER planner,
  telemetry, adaptive resources, multi-node policy, OpenSSH, qdel, and live.
- **Stop rules:** Stop for a required upstream public API/schema change, new
  retry/effect authority, production dialect guess, trust-model change, or live
  evidence required to choose semantics. Production qualification must come
  only from the separately accepted exact preflight evidence.
- **Non-goals:** No live RTwin/SSH/PBS/Gaussian, qsub/qstat, deployment,
  credentials, host-key acceptance, qdel/delete/cleanup, automatic retry,
  resource planning, or scientific interpretation.

### `V30-PBS-TORQUE-DIALECT-01`

- **Outcome:** Replace the production-dialect preflight blocker with one exact
  source-controlled Torque `6.1.0` single-node `nodes:ppn` renderer for the
  first V30-A deployment.
- **Authority:** Owner-approved two-phase lane: docs-only freeze and independent
  contract review first; only after normal integration may the bounded
  Transport implementation, focused/affected validation, independent review,
  and normal integration proceed autonomously.
- **Contract scope:** Exact authority files only: `OWNER_DECISIONS.md`,
  `docs/v3/boundary-spec.md`, `docs/v3/acceptance.md`, this file,
  `docs/v3/STATUS.md`, and `config/context-map.toml`.
- **Implementation scope:** Existing Transport-owned dialect/renderer/bootstrap
  boundary and `tests/v3/transport/**` only. No upstream public API/schema
  change.
- **Dialect:** Exact ID
  `auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1`; exact argv is
  `-l`, one `nodes=1:ppn=C,mem=Mmb,walltime=W` value, `-q`, exact queue, then
  exact PBS basename. Integer MB and seconds replay without conversion.
- **Queue:** The first deployment requires exact `batch`; null or any other
  queue rejects. Observed scheduler defaults never become authority.
- **Executable evidence:** Manifest-only `server_qsub` is
  `/usr/local/bin/qsub`, 418920 bytes, SHA-256
  `f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d`;
  `server_qstat` is `/usr/local/bin/qstat`, 185656 bytes, SHA-256
  `3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a`.
  No package identity is invented.
- **Safety:** Synthetic remains non-live; production qualification alone grants
  no live effect. PBS resource directives remain forbidden, WINNER remains the
  sequencing gate, REPLAY is zero qsub, and UNKNOWN grants no retry.
- **Validation:** Exact three positive renderer vectors, closed negative matrix,
  qsub/qstat drift tests, affected synthetic composition delta, static/diff/
  sensitive checks, and fresh independent reviews at `0/0/0/0`.
- **Stop rules:** Stop for any upstream API/schema change, incompatible
  one-node/memory semantics, required extra scheduler resource/authority,
  changed qsub/qstat identity, or two failed same-class repairs.
- **Non-goals:** No generic PBS abstraction, multi-node policy, alternate
  queue, resource planner/telemetry, OpenSSH, deployment, live qsub/Gaussian,
  retry, qdel, deletion, or cleanup.

### `V30-TRANSPORT-RTWIN-LAUNCHER-MULTILINE-BOOTSTRAP-QUOTING-REPAIR-01`

- **Outcome:** Preserve the generic LF-rejecting POSIX token contract while
  giving only the exact attested fixed bootstrap one deterministic multiline
  single-argv quoting seam.
- **Authority:** Owner-guided maintenance through contract freeze, narrow
  implementation, focused/affected/synthetic validation, two independent
  reviews, normal integration, and exact-main closeout. Deployment is excluded.
- **Scope:** `auto_g16/transport/_bridge.py`, directly required Transport tests,
  and the minimum v3 authority/status documents. No upstream public API/schema.
- **Identity:** Successor launcher logical name is
  `auto-g16-v3-rtwin-launcher-v2.ps1`, 8576 bytes, 140 LF, SHA-256
  `1e6a8210...`; manifest schema/protocol v2 and the exact ten-root model
  remain. Bootstrap bytes remain exact 15562-byte
  `ad0ba2af...`; revision 4 binds the new launcher/manifest identities.
- **Validation:** Prove generic LF rejection, exact-bootstrap-only entry,
  strict UTF-8 byte roundtrip, one-word POSIX reconstruction, special-character
  literalness, Python 3.6 compile, unchanged inner length bound, focused and
  affected Transport, and synthetic V30-A composition.
- **Stop rules:** Stop for generic quoter weakening, bootstrap-byte or protocol
  change, manifest schema change, inner-bound overflow, upstream API/schema
  change, or two failed same-class repairs.
- **Non-goals:** No deployment, RTwin persistent write, workspace/staging,
  qsub/Gaussian, retry, qdel, cleanup, new Attempt, generic multiline shell, or
  caller-controlled execution surface.

### `V30-TRANSPORT-AGV3-EOF-INDEPENDENT-FORWARDING-01`

- **Outcome:** Replace the revision-4 launcher's EOF-dependent stdin copy with
  exact AGV3 header/length/payload acquisition before nested SSH, then exact
  write/flush/immediate nested-stdin close independent of outer EOF.
- **Authority:** Owner-guided maintenance through contract freeze, narrow
  product repair, focused/affected/composition validation, fresh independent
  adversarial review, normal integration, exact-main attestation, and revision-5
  deployment-packet preparation. Deployment and live qualification are excluded.
- **Scope:** `auto_g16/transport/_bridge.py`, directly required
  `tests/v3/transport/**`, and the minimum five v3 authority/status documents.
  No upstream public API/schema or selector change.
- **Identity:** Successor launcher is
  `auto-g16-v3-rtwin-launcher-v3.ps1`, 9579 bytes, 161 LF, SHA-256
  `7247beda...`; one successor manifest-v2 content instance and ServerProfile
  revision 5 bind the new launcher. Bootstrap/table/protocol `/2` and the exact
  ten-root inventory remain unchanged.
- **Safety:** No nested process exists until the complete capped frame is
  acquired. Bad magic, oversized length, or partial header/payload is zero
  nested connection. Bounded stdout/stderr drains and the one finite input
  write run concurrently after nested start; input completion closes nested
  stdin without duplex backpressure or outer-EOF dependence. The launcher never
  interprets AGV3 authority or reads beyond the declared frame. The bootstrap
  retains final EOF enforcement; Controller output remains exactly one frame.
- **Validation:** Prove open-outer-stdin completion and ordering; closed header
  negatives; full-length mutation forwarding/bootstrap rejection; unchanged
  quoting, attestation, Python 3.6, binary channel, REPLAY/UNKNOWN, qsub-once,
  Torque, and synthetic composition evidence; independent `0/0/0/0` review.
- **Residual process gate:** Before a future deployment/qualification, exact
  read-only reconciliation must prove prior residual count zero. Nonzero count
  requires a separate exact-process termination gate. No broad kill or cleanup.
- **Stop rules:** Stop for protocol/bootstrap semantics change, inability to
  acquire under the frozen cap, upstream public API/schema change, nested start
  before full frame, deployment/live requirement, or two failed same-class
  repairs.
- **Non-goals:** No deployment, nested real qualification, workspace/staging,
  qsub/Gaussian, retry, qdel, deletion/cleanup, recovery Attempt, OpenSSH, or
  generic transport redesign.

### `V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01`

- **Outcome:** Mechanically integrate the already-qualified Mac
  `/usr/bin/ssh` plus one RTwin `ProxyJump` route and freeze ServerProfile
  revision 8. Windows nested-stdin routes remain historical and are never an
  Option-1 fallback.
- **Reuse:** KEEP AGV3 framing/decoding, TransportStore, Core/effect semantics,
  bootstrap, resource/PBS authority, Observe/Result; WRAP the existing bounded
  subprocess supervisor; PORT exact Mac OpenSSH/config/trust/identity-reference
  mechanics; REPLACE only the profile-selected Windows nested command route.
- **Scope:** Private Transport bridge/driver helpers, focused Transport tests,
  and the minimum authority/status/context documents. No public API/schema,
  protocol, bootstrap, trust-root, or authority change.
- **Identity:** Bind `/usr/bin/ssh`, 1584576 bytes, SHA-256 `17542914...`, and
  final-key public fingerprint `SHA256:aqyVwyOa9wRiA93G52/rirqt/8ktUhUfX2Cja709w/s`.
  The exact public-key artifact and qualified private-file physical identity
  are profile-bound. Private keys remain local mode-0600 references whose bytes
  are never read. Both hops require `CertificateFile none`, closing implicit
  sibling user-certificate discovery.
- **Validation:** Focused Option-1 vectors, affected Transport/composition,
  static and sensitive-data audits, independent `0/0/0/0` review, Required CI,
  and CodeQL. Normal merge is authorized when exact-main compatibility passes.
- **Non-goals:** No deployment, new Attempt/approval/snapshot, workspace,
  qstat/qsub, Gaussian, qdel, cleanup, automatic retry, global SSH config
  mutation, agent forwarding, generic framework, or architecture exploration.

### V30-EXEC-PBS-WORKDIR-ENACTMENT-CONTRACT-01

- **Outcome:** Enact the exact snapshot-bound Attempt workspace as both qsub
  client cwd and scheduled Torque shell cwd, with named-path physical replay
  immediately before qsub.
- **Scope:** Private Transport renderer, fixed bootstrap, operation-table and
  runtime identities, focused/affected tests, minimum authority/status/context
  docs, and append-only future acquisition evidence closeout.
- **Preserve:** Existing `SUBMIT_QSUB_ONCE` request schema, AGV3 `/2`, ten-root
  trust model, public APIs, resource sole authority, at-most-once submission,
  `REPLAY` zero effect, and `UNKNOWN` no retry.
- **Stop:** Any public API/protocol/schema/trust change, live deployment,
  scheduler read, fetch, retry, cleanup, or new calculation Attempt.

### V31-SHARED-CONTRACT-01

- **Outcome:** Freeze the smallest shared v3.1 contract for Project first-use
  physical provisioning, an additive versioned execution successor required
  for xTB/CREST, conformer handoff, thermodynamic handoff, and deterministic
  TS-seed member projection. V30 Gaussian execution remains production-usable;
  V31 acceptance does not require Gaussian migration.
- **Scope:** `OWNER_DECISIONS.md`, the minimum `docs/v3/**` authority documents,
  and `config/context-map.toml` only when required for authoritative routing.
  Contract text may define future public shapes but creates no product or
  schema implementation.
- **Public budget:** At most two new execution-domain public records:
  `ProgramExecutionSpec` and `ProgramExecutionSnapshot`. Provisioning-domain
  `ProjectPhysicalBinding` is separate. ProgramAdapter is a private closed
  registry for exactly Gaussian/xTB/CREST. Ensemble-domain public records are
  `SamplingProfile`, `ConformerEnsemble`, and
  `ThermodynamicEnsemble`; TS-seed projection stays
  `ConformerEnsemble.ts_seed_members`.
- **Generation routing:** One V31 Workflow/Batch may intentionally contain V30
  Gaussian Attempts and successor-generation xTB/CREST Attempts. Each Attempt
  binds exactly one generation before effect authority, never both, with no
  in-place conversion. A future Gaussian successor requires a separate adapter
  implementation/validation gate and is not an initial V31 acceptance target.
- **Preserve:** V30 `PreparedInputBinding`, `PbsTemplateBinding`, and
  `ExecutionSnapshot`; Core Project shape/schema; Transport topology/protocol;
  parser/grammar and Result meanings; V30 vectors; approval/effect/no-overwrite/
  uncertainty semantics.
- **Policy:** SamplingProfile independently freezes all applicable thresholds
  and policies before observations. Thermodynamics separately preserves raw
  RRHO, per-conformer treated qRRHO, and final degeneracy-weighted ensemble
  aggregation with no unverified defaults or duplicated conformational entropy.
- **Autonomy:** `OWNER-GUIDED`, contract-only and zero-effect. The explicit
  Owner boundary authorizes the contract candidate, offline validation,
  independent review, and one local commit only.
- **Validation:** docs/contract-focused checks, authoritative selector result,
  the selector-required v3-full tests once on the frozen candidate, static/CI
  contract/diff/sensitive checks, clean preflight, and fresh independent
  findings-first review. P0/P1 block.
- **Stop rules:** Stop on base/tree drift; a third execution public record;
  public adapter/plugin surface; hard-coded universal threshold/default;
  in-place V30 reinterpretation; any implication that all V31 Gaussian Tasks
  migrate; Core/Transport/parser/vector/product/test mutation; implementation
  or live need; or any P0/P1.
- **Handoff:** Local commit with exact base/head/tree/diff/test/review evidence
  and PR-ready scope. Do not push, create a PR, merge, deploy, provision, run a
  program, submit, retry, clean up, or accept science.


### V31-PBS-COMPAT-FILE-COMPLETION-01

The phase and candidate labels below are retained checkpoints, not the current
implementation status. [PR #173 integration](STATUS.md#file-completion-implementation-checkpoint)
and the [freeze dossier](pbs-file-completion-freeze.md) record the later
C2/C3/C4 implementation and evidence cutoffs. No contract or acceptance vector
is retired, and the historical opening instruction is not renewed.

- **Class / autonomy:** Feature development; v3; OWNER-GUIDED. Ordinary Codex
  app isolated task, not a BUS Executor; no CTRL/Control Issue is created.
- **Outcome:** Freeze OD-32 and the exact receipt-on-absence boundary for new
  xTB successor Attempts, then perform the smallest offline implementation
  only after actual independent review and repository Owner L3 freeze.
- **Current authority:** User authorized this ordered contract-first work,
  local documentation, necessary review and local freeze commit. This grants
  no generic permission to choose an unresolved safety contract or to claim
  that Owner reviewed the eventual content. No further user task is created.
- **Phase 1 allowed paths:** `OWNER_DECISIONS.md`,
  `docs/v3/boundary-spec.md`, `docs/v3/acceptance.md`,
  `docs/v3/AUTONOMOUS_DEVELOPMENT.md`, `docs/v3/STATUS.md`,
  `config/context-map.toml`, and
  `docs/v3/pbs-file-completion-freeze.md` (content manifest, review and handoff).
- **Phase 2 proposed paths (inactive until freeze):**
  `auto_g16/execution/program.py`, `auto_g16/execution/program_runtime.py`,
  new private `auto_g16/execution/_program_completion.py` and
  `auto_g16/execution/_program_completion_wrapper.py`,
  `auto_g16/transport/program.py`, `auto_g16/transport/_program_rtwin.py`,
  `tests/v31/transport/test_program_composition.py`,
  `tests/v31/transport/test_rtwin_successor_bridge.py`,
  new `tests/v31/transport/test_program_completion.py`, and the phase-1 docs
  for evidence only. Existing marker/bootstrap protocol and schemas do not
  change. Any newly discovered required path is an explicit scope decision.
  Real receipt-mode drivers/evaluation stay hard-disabled pending a separate
  publisher qualification contract/gate; synthetic offline completion only is
  acceptance scope for this implementation. Existing strict production is
  unchanged. No user-selectable qualification override is added.
- **Dependencies / reuse:** REWRITE only mode/rendering/receipt evaluator;
  WRAP existing STAT/FETCH and raw acquisition; EXTRACT existing canonical
  identity and no-follow/exclusive publication primitives; keep Core,
  Approval, Result, Observe schemas and existing successor composition owners.
  No legacy v2 owner/capability framework, new public record or extension bag.
- **Compatibility / migration:** Default strict and historical serialized IDs
  remain exact; new adapter version is opt-in on fresh Attempts. No migration
  command, historic job read, historic result rewrite, CREST integration or
  Gaussian generation change. Unsupported downstream consumers reject `/2`.
- **Review / stop:** L3 scheduler/security boundary. Independent technical
  review is required but does not replace repository Owner review. Freeze
  exact six authority-file hashes plus a local candidate commit and preserve
  review evidence in the dossier. P0/P1, mismatched hashes, Owner decision
  missing, drift or an unclosed dependency stops before product edits. The
  Owner decides the publisher trust model, absence/terminal conflict policy,
  and execution-output/scientific boundary by accepting the exact candidate.
- **Sequencing:** The implementation is the second checkpoint of this same
  task/worktree, not a separately developed lane; no prior merge is required
  by this task. If review instead requires independently isolated code work
  or prior integration, hand off exact frozen material and that blocker, and
  stop without creating a new user task or modifying shared main.
- **Validation:** preflight before edits; contract static/link/TOML/diff and
  CI audit; focused/affected implementation vectors FC01–FC15 after freeze.
  No blind full, remote CI, pressure test or live test. Handoff distinguishes
  static evidence, independent review, Owner freeze, implementation and live.
- **Forbidden:** push, PR, merge, deployment, release, SSH, RTwin, PBS,
  xTB/CREST/Gaussian execution, qsub/qdel, remote writes, cleanup or scientific
  acceptance. Synthetic offline wrapper process tests may use only inert
  fixture children; they grant no program/live authority.
- **Disposition:** CANDIDATE; repository Owner exact-candidate freeze pending.
  Local worktree/branch retained; cleanup and archival are not authorized.

#### C3 material-derivation checkpoint

Historical checkpoint; see the [later implementation disposition](STATUS.md#file-completion-implementation-checkpoint).
The material-derivation requirement remains part of the accepted contract.

C2 Owner acceptance activates phase 2, but implementation discovery of the
manifest-content gap stops the dependent renderer at a P1 contract boundary.
C3 proposes only the private material input/data-line/prebinding delta defined
in the boundary supplement, within the existing allowed paths. No public
record, Transport operation, deployment, production qualification or live
permission is added. C3 remains an exact Owner review checkpoint; it is not
an autonomous reinterpretation of accepted C2. Isolated pure receipt grammar
work already started is retained as incomplete work, not an implementation
PASS. Do not activate C3-dependent code before the new review closes.


#### Authorized A/B follow-up and proposed C4 activation

Historical A/B opening and C4 proposal checkpoint; see the
[later C4 disposition](STATUS.md#v31-file-completion-c4-proposal-status).
The original conditional gate below is retained, not reopened.

The Owner authorized this same task to repair only
`config/validation-selection.json`, `tests/test_validation_selector.py` and
necessary evidence docs (A); and to prepare/review the C4 proposal in the six
phase-1 authority files and dossier, with credential-free local native probes
(B). Selector/runner/workflows/required checks remain immutable. Necessary
local checkpoint commits use normal hooks and staged scans; no automatic full
run, push, PR, merge, deployment, live operation or cleanup is authorized.

**C4: PROPOSED / OWNER ACCEPTANCE PENDING.** B does not accept an unwritten
contract. After independent review, freeze exact six-file hashes and a local
candidate commit for Owner decision. On explicit acceptance of those exact
bytes, the proposed next phase is only the C4 offline implementation in
`auto_g16/transport/program.py`, `auto_g16/execution/program_runtime.py`,
`tests/v31/transport/test_program_completion.py`,
`tests/v31/transport/test_program_composition.py`, plus phase-1 evidence docs.
Reuse public Core calls and existing transport authority; no new module, public
API/schema, factory default change, VFS override or product provisioning path.
The only new persistent schema is the exact private `/2` store described by C4.
Any additional necessary product path or unresolved design change stops for a
bounded scope/contract decision. Prior C2/C3 product bytes stay frozen during B.

Use focused C4 vectors on the native Mac with inert fixtures and default SQLite,
adjacent strict compatibility and exact-base/head selection; obtain independent
review of exact product bytes. No full acceptance claim from primitive probes,
no old-store migration and no production qualification override. C4 acceptance
would authorize this bounded offline implementation, not creation of real
operational stores, live tests or acceptance of eventual implementation results.


### V31-PUBLISHER-R4-OFFLINE-IMPLEMENTATION-01

[PR #174](STATUS.md#verified-integration-evidence) subsequently integrated the
offline implementation. The accepted R4 precedence and qualification boundaries
below remain binding; that integration grants no new installation or live scope.

Owner accepted the exact reviewed R4 package on 2026-09-15 for bounded offline
product implementation. The [frozen Task Contract and provenance](publisher-r4/README.md)
close scope, R4 > R3 > R2 precedence, validation and remaining gates. Earlier
publisher hard stops remain for unqualified production; this acceptance permits
the private qualification/tuple/Controller implementation, not target qualification
or activation. Preserve the original synthetic v3 completion and strict behavior.
Approval semantics stay in Controller; Transport reads only fixed deployment
identity evidence. Actual deployment locator and host facts are NOT_ACQUIRED.


### V31-SAME-ATTEMPT-COLLECT-RECOVERY-01

[PR #175](STATUS.md#same-attempt-collection-recovery-c2) subsequently integrated
the implementation. The original C2 base, validation and operational boundaries
below remain source-bound; they do not open another collection epoch or Attempt.

- **Class/base:** v3 feature, bounded autonomy after C2 freeze, L3 boundary;
  exact R4 base `8d49ef23e7c74c4333c551e81461e3f0921948ab`, tree
  `6141c8ef3764fa54d1b5705bc303b8c9f6abc0c9`.
- **Authority:** coordinating task's 2026-09-16 delegated technical acceptance
  of C2 design SHA256 `e1201350faecea03bee20e4ab2a3a92bd8d5bdea4385655f31507338b110b70b`;
  independent exact PASS recorded in the [frozen contract](same-attempt-collection-recovery-contract.md).
- **Scope:** only that contract's four private product modules, named transport
  tests and authority references; no additional lane, public record or schema.
- **Validation:** CR01–CR09 plus necessary affected checks, independent review
  and exact candidate selection. Conservative legacy-release routing is reported
  without an automatic full run or bypass. Prior checks are not reassigned.
- **Operational boundary:** parent coordinates concrete new local installation
  and same-job CR10; implementation author makes no real DB or remote changes.
- **Stop:** no new Attempt, claim/qsub, provisioning/staging, remote mutation,
  cleanup, automatic retry, original approval/window change, CREST, publication
  or merge. Scope/API gaps require a reviewed narrow delta.
- **TP01–TP06 delta:** the Owner's 2026-09-22 instruction permits only an
  asynchronous local progress reporter in the existing `_program_rtwin.py`
  collection-owned FETCH path and its named affected test. It may not run in
  the transport I/O/deadline thread or change any driver/wire/result meaning.
- **IR01–IR08 delta:** the same instruction permits private recovery of the
  sole latest unmatched successful present-file STAT through its exact existing
  FETCH request before one clean collection epoch. Work is limited to
  `program_runtime.py`, the named recovery test and authority references. Every
  remote application requires a fresh reviewed continuation; no automatic retry,
  state repair, deletion, submission or new Attempt is permitted.

### V31-CREST-LIVE-CLOSURE-01

BOUNDED-AUTONOMOUS within the [exact design freeze](crest-live-closure-freeze.md).
The Owner explicitly delegated technical/exact approval after independent
review. Follow the frozen scope and three product approval gates. No automatic
retry, qdel, cleanup, broader science, publication or merge is authorized.

### V31-CREST-695-MARKERLESS-RECOVERY-01

Bounded v3 feature/L3 offline implementation under the delegated freeze recorded
in [the recovery contract](exact-observed-job-recovery-contract.md), based on
`ceff406def65b575babb898d51683c47238c91fb` in an isolated worktree. Preserve the
producer worktree and original stores. Scope is private recovery/restore,
focused adversarial tests and authority references. Require independent review
of the precise final candidate and proportional validation. Local commit is
allowed; publishing, merge, actual installation, real-store mutation and all
remote operations are reserved to the parent and their separate exact gates.
