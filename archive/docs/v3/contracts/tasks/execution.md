# Auto-G16 v3 tasks: execution

Component of [AUTONOMOUS_DEVELOPMENT.md](../../AUTONOMOUS_DEVELOPMENT.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:197-221 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

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

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:410-453 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

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
