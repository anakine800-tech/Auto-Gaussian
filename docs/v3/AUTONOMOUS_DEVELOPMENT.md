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

1. `V30-EXEC-02-COMPOSITION-CONTRACT-01` — integrated
2. `V30-VAL-TRANSPORT-01` — integrated
3. freeze/integrate `V30-TRANSPORT-BOOTSTRAP-CHAIN-03`
4. successor V30-EXEC-02 Transport implementation
5. `V30-A-SYNTHETIC-COMPOSITION-01` test-only integration after Transport main
6. `V30-A-READINESS-01` repeat audit before any live gate

The control structure remains serial at integration:

```text
Integration Owner
└── V30-EXEC-02-COMPOSITION-CONTRACT-01
    -> V30-VAL-TRANSPORT-01
    -> V30-TRANSPORT-BOOTSTRAP-CHAIN-03
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
