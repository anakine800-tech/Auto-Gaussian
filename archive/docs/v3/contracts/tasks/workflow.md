# Auto-G16 v3 tasks: workflow

Component of [AUTONOMOUS_DEVELOPMENT.md](../../AUTONOMOUS_DEVELOPMENT.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:248-291 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

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
