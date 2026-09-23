# Auto-G16 v3 boundary: approval

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:129-292 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-3A Frozen Approval Authority Contract

**Contract status: FROZEN; IMPLEMENTATION INTEGRATED ON
`main@4a181871b0894161dd74fe91c405aa35e3691fd6`.** Approval belongs to a
Workflow/Controller layer. It does not add an
`auto_g16.core` record, store method, state transition, schema table, or effect
owner, and it does not reopen the frozen Execution or Result contracts. The
approval-layer package is `auto_g16.approval`, with focused tests under
`tests/v3/approval/`. It may depend on the public `auto_g16.core` and
`auto_g16.execution` surfaces; neither Core nor Execution may depend on it.
Workflows or a Controller compose the approval layer with execution. V30-3A
fixes package ownership, authority, and invalidation semantics; V30-3B
separately reviewed and integrated the public type shapes, persistence, and
implementation without changing this contract.

The only legal approval-to-effect chain is:

```text
exact CalculationPlan
-> current Scientific Approval
-> Batch Submit Approval membership for the exact Attempt and plan
-> exact ExecutionSnapshot
-> current Exact Operational Confirmation
-> Controller validates the complete current chain
-> execute_once(exact snapshot and bytes)
   -> record_submission_intent(exact Attempt, exact submission intent)
   -> explicit Core WINNER
   -> first effect
```

No item in this chain may stand in for another. An approval record, a
confirmation record, a digest, an `ExecutionSnapshot`, `REPLAY`, or adapter
readiness cannot replace Core `WINNER`.

### Scientific Approval

Scientific Approval binds all of these semantics as one closed decision:

```text
calculation_plan_id
task_id
positive calculation_plan_revision
expanded canonical CalculationPlan.intent
the displayed semantic meaning reviewed by the human
explicit approved decision and reviewer identity/evidence
```

The displayed meaning must be derived from that exact plan and must be
sufficient for a reviewer to understand the current scientific intent;
presentation-only formatting bytes are not a second scientific authority. An
implementation may record a digest for identity or audit, but it must replay
the expanded plan, semantic view, explicit decision, and reviewer evidence
before treating approval as current. A matching hash alone is never approval
authority.

A different plan ID, revision, task binding, canonical intent, or displayed
semantic meaning makes the earlier approval inapplicable to the changed plan.
Manual edits follow OD-02: parse the current input again, display the semantic
diff, and obtain approval for the resulting current CalculationPlan. Resource,
ServerProfile, workspace, PBS-template, and ExecutionSnapshot values are not
scientific-approval fields and their change is not automatically a scientific
change.

Scientific Approval is plan-scoped rather than Attempt-scoped. Creating a new
Attempt does not by itself invalidate it. A later Attempt, including an
explicit recovery child, may rely on the same scientific approval only when it
still resolves to the exact same plan ID, task, revision, canonical intent, and
displayed meaning. It gains no submit permission from that fact.

### Batch Submit Approval

Batch Submit Approval binds one explicit, finite, non-empty set. Every member
contains the exact:

```text
attempt_id
task_id
calculation_plan_id
calculation_plan_revision
Scientific Approval identity/evidence for that exact plan
explicit approved decision and reviewer identity/evidence for the closed set
```

All listed Attempts must already exist and resolve through the frozen Core
ownership relationships. An optional Core `Batch` identity is organizational
context only; it never expands membership to every current or future task or
Attempt in that Batch. Membership is exact and cannot use a query, prefix,
range, future placeholder, or "all current members" rule.

One human decision may cover multiple listed Attempts, but the decision is not
a database, scheduler, or effect transaction. Each member independently passes
later gates. Failure, `UNKNOWN`, non-submission, or staleness of one member does
not authorize a replacement and does not expand or silently rewrite the set;
it also does not by itself revoke another unchanged member's exact scope.

An unlisted root, replacement, or child Attempt is rejected. A changed plan or
scientific approval makes that member's listed binding stale. Creating a child
Attempt after `FAILED` or `NOT_SUBMITTED` always requires new explicit Batch
Submit Approval membership, even when the exact scientific approval remains
applicable. An `UNKNOWN` Attempt creates neither a child nor retry authority.

Batch Submit Approval intentionally does not bind resource values,
ServerProfile content, workspace paths, PBS-template bytes, or an
ExecutionSnapshot. Those values are checked by exact operational confirmation.
Changing them within an approved operational policy does not silently change
science or Batch membership, but it cannot reuse a stale snapshot confirmation.
This contract neither defines nor bypasses the separate resource policy.

### Exact Operational Confirmation

Exact Operational Confirmation binds one and only one fully resolved
`ExecutionSnapshot`, plus the confirmer identity/evidence and explicit human
confirmation of that exact snapshot. The reviewer must be shown the exact
Attempt and the snapshot's effect-relevant values, including:

```text
execution_snapshot_id
attempt_id and submission_intent_id
calculation_plan_id and revision
exact prepared-input identity and bytes digest/size
resolved resource request
resolved ServerProfile target and effect-relevant configuration identity
Attempt workspace binding
validated exact PBS-template identity
adapter contract version
```

The confirmation is valid only while the complete snapshot identity closes
over those exact values. Any snapshot or nested binding change, including
resource, profile/target, workspace, input, template, adapter-contract, or
submission-intent drift, makes the earlier confirmation stale and requires a
new resolution and confirmation. The unchanged exact confirmation may be
replayed deterministically for validation; replay creates no additional effect
or retry authority.

### Effect gate, replay, and invalidation

Immediately before invoking Execution, the Controller must replay the exact
current Scientific Approval, exact Batch Submit Approval member, and exact
Operational Confirmation against the same Attempt, plan, and snapshot. Missing,
conflicting, malformed, stale, cross-Attempt, cross-plan, or cross-snapshot
evidence fails closed before `execute_once(...)`, the Core claim, and every
external effect. The Controller must not pre-claim submission intent.

Approval alone performs no Core transition, workspace mutation, upload,
submission, retry, reconciliation, cancellation, cleanup, or deletion.
Confirmation alone is also non-effectful. Even a complete approval chain makes
zero submission effect unless the claim owned inside `execute_once(...)`
returns `WINNER`; `REPLAY` and every non-winner path make zero effect calls.

Exact replay of unchanged approval evidence is deterministic and idempotent;
the same evidence identity with different content conflicts. Approval evidence
is durable review evidence, not a batch transaction, receipt owner-chain,
single-use capability forest, or hash-lineage authority. The integrated V30-3B
implementation does not port those legacy governance mechanisms as an implicit
requirement.

An ambiguous submission remains `UNKNOWN` under the frozen Core and Execution
contracts. It authorizes only read-only same-Attempt reconciliation, never an
automatic retry, replacement Attempt, new Batch membership, new confirmation,
or second effect. Recovery continues through an explicitly created child after
the Core terminal-state rules permit it, followed by the approval gates stated
above.
