# Auto-G16 v3 acceptance: approval

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:72-140 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-3A: Approval Authority and Invalidation Contract

**Status: SATISFIED / INTEGRATED ON
`main@4a181871b0894161dd74fe91c405aa35e3691fd6`.** The conditions below
remain the frozen approval authority contract. They require no Core API/schema
change and perform no external effect:

1. Scientific Approval binds the exact CalculationPlan ID, task, positive
   revision, expanded canonical intent, displayed semantic meaning, explicit
   approved decision, and reviewer identity/evidence. Exact unchanged replay
   is deterministic and idempotent; conflicting content under the same evidence
   identity fails closed.
2. A different CalculationPlan ID, revision, task binding, canonical intent,
   or displayed semantic meaning makes the prior Scientific Approval
   inapplicable to the changed plan.
3. Manual input editing is reparsed into the current semantic plan, displays
   the semantic diff, and requires approval for that current plan. Matching
   artifact hashes alone cannot keep or create approval.
4. Resource, profile/target, workspace, PBS-template, or ExecutionSnapshot
   change is not automatically classified as a scientific change and cannot
   silently modify the approved CalculationPlan.
5. Batch Submit Approval contains an exact finite non-empty list of existing
   Attempts, an explicit approved decision, and reviewer identity/evidence.
   Each member binds its exact task, CalculationPlan ID/revision, and current
   Scientific Approval; one review may approve multiple exact members.
6. An Attempt not listed in the exact set is rejected. Batch identity, a
   prefix/query/range, a future placeholder, or later Batch membership cannot
   expand the approved set.
7. A replacement or recovery-child Attempt is rejected by the parent's Batch
   Submit Approval. A child always requires new explicit membership; the exact
   unchanged Scientific Approval may remain applicable only when the child's
   plan binding is identical.
8. Batch Submit Approval is not a transaction. Failure, `UNKNOWN`, or
   non-submission of one member grants no replacement/retry authority and does
   not expand another member's scope.
9. Exact Operational Confirmation binds one exact ExecutionSnapshot, explicit
   human confirmation and confirmer identity/evidence, plus all nested
   effect-relevant input, resource, profile/target, workspace, PBS-template,
   adapter-contract, Attempt, and submission-intent semantics.
10. Exact unchanged Operational Confirmation replay is deterministic and
    non-effectful. Any snapshot or nested binding change makes the prior
    confirmation stale and is rejected before a Core claim or external effect.
11. Scientific Approval alone, Batch Submit Approval alone, and Exact
    Operational Confirmation alone each produce zero Core transitions and zero
    filesystem, transport, scheduler, PBS, or Gaussian effects.
12. The complete current approval chain still produces zero submission effect
    unless the exact Core claim returns explicit `WINNER`; `REPLAY`, rejection,
    and every non-winner path make zero adapter/effect calls.
13. Missing, malformed, conflicting, cross-Attempt, cross-plan, stale, or
    cross-snapshot evidence fails closed before Core claim and effect.
14. `UNKNOWN` never creates scientific, Batch Submit, confirmation, child, or
    retry authority and permits only the frozen read-only same-Attempt
    reconciliation path.
15. Approval evidence may use hashes for artifact identity or audit, but no
    hash, receipt, legacy owner-chain, capability, or lineage record substitutes
    for semantic replay of the three current approval gates.
16. Contract tests for V30-3B must cover plan-change staleness, unchanged replay,
    unlisted and future-child rejection, exact multi-Attempt membership,
    snapshot-change staleness, zero-effect isolated approvals/confirmation,
    explicit `WINNER`, and UNKNOWN no-retry behavior.
17. Approval implementation is owned by `auto_g16.approval`, with focused tests
    under `tests/v3/approval/`. It may depend on public Core and Execution
    surfaces; neither Core nor Execution imports the approval layer, and no
    approval record or state is added to the Core schema.

V30-3A stops after independent contract review and repository publication.
V30-3B implementation is integrated without changing these conditions;
completion does not authorize V30-EXEC-02, deployment, or live execution.
