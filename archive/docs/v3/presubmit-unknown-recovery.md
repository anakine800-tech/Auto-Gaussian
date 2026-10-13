# Auto-G16 pre-submit UNKNOWN recovery

Owner scope: implement and validate recovery of an interrupted pre-submit
transfer, then explicitly resubmit one unchanged anti calculation. This is a
v3 feature in an isolated `codex/presubmit-unknown-recovery` worktree based on
`b4c7ccb5faab0bb412946c226e834c196068e826`. Local implementation, offline checks,
the original-store recovery and one separately bound child submission are
authorized; publication, merge, deletion and automatic retry are excluded.

The additive recovery is local and Execution-owned. It acquires the existing
cross-process completion guard, replays the original snapshot, intent,
qualification and complete Core/Transport effect prefix. Admission requires
one successful allocation, an ordered nonempty prefix of declared stages,
successful predecessors and exactly one final UNKNOWN stage. Every physical
effect for the Attempt must have a corresponding native receipt. An absent
scheduler job alone is never evidence of non-submission.

The producer executes allocation, stages and qsub synchronously under that
same guard. A durable final UNKNOWN stage plus Core UNKNOWN proves that the
producer exited its exception branch before qsub. This proof says nothing
about whether the uncertain stage wrote bytes. All remote data remain intact.
An ambiguous allocation, qsub outcome, incomplete dual-store pair, extra
effect, active producer, drift or conflicting history must fail closed.

One append-only native Observation binds the original receipt prefix,
snapshot, original intent, exact stopped receipt and explicit recovery
decision. Core's existing reconciliation operation resolves UNKNOWN to
NOT_SUBMITTED. A crash after the Observation but before Core disposition
allows only exact local proof replay, with no new effect. No schema migration,
producer change, remote call, child creation or submission occurs in recovery.
The caller must still explicitly create a child, preserve the same Task/Plan,
obtain current finite Batch membership and exact snapshot confirmation, and
enter the sole execute_once path. The consumed parent can never restart.

Validation covers success, replay/crash replay, unchanged historical receipts,
qsub/allocation uncertainty rejection, missing/extra physical effects, wrong
decision/receipt, and zero driver calls during recovery. Existing native
locking and effect/approval tests remain required adjacent coverage. Live
evidence concerns exact local original-store proof closure and a separately
authorized child run; historical target qualification is not described as a
rerun. No scientific acceptance follows from recovery or submission.

## Integration continuation

The initial authorization above is retained history. On 2026-10-12 Owner
explicitly requested completion of all four remaining items (unified execution
entry, frontend, engineering merge/deployment, fresh E2E). This authorizes
preparation of this existing dependency for integration after independent L3
review and required validation; it does not waive exact scientific/live gates.
Task PRESUBMIT-UNKNOWN-INTEGRATION-01 is OWNER-GUIDED, non-BUS, based on the
same `b4c7ccb5faab0bb412946c226e834c196068e826` and isolated branch. This delegated
slice may edit this contract, Owner/boundary/acceptance/context-map, validation
routing and its tests, and local synthetic recovery tests. It stops at evidence
handoff; no commit, push, merge, deployment, remote access or new calculation
is performed by this implementer. The coordinating integrator retains the
Owner-authorized later steps. No Study implementation is added here.

## Exact recovery boundary

Private `execution._presubmit_recovery.reconcile` accepts the original Core,
exact snapshot, original Transport, qualified driver, stopped_receipt_id, an
explicit decision and boolean apply (default true). The closed decision keys
are reviewer_id, evidence, attempt_id, snapshot_id, decision; the last equals
reconcile-not-submitted and the identities must match. reviewer_id and evidence
are nonempty strings; they record the explicit operator decision, not a newly
created approval. The fixed Controller additionally rechecks original native
scientific/finite-Batch/operational authority and pinned recovery source before
local mutation. `apply=False` returns the exact proposed Observation without
persistence; it never performs remote inspection.

Admission is UNKNOWN or exact NOT_SUBMITTED proof replay. The native owner
reconstructs every receipt request and response from the original snapshot,
intent and predecessors and matches the complete physical-effect set (including
no hidden qsub fact). The proof schema v31-presubmit-reconciliation/1 has
exactly schema,attempt_id,snapshot_id,effect_intent_id,stopped_receipt_id,
receipt_ids,observation_prefix_sha256,decision,resolution,scope; resolution is
NOT_SUBMITTED and scope is `qsub-not-reached; staged bytes may exist`. Its native
semantic Observation identity and original prefix bind all fields. The sole
proof is appended before Core reconciliation. Replay requires the identical
proof, identical decision and no later parent observations; it never records a
new SubmissionIntent or child. Existing UNKNOWN records remain intact.

`scripts/reconcile_v31_presubmit_unknown.py` is the fixed Controller function
`reconcile_fixed`, not a user CLI or automatic recovery service. A later unified
entry must adopt this owner under its own frozen authority; this dependency
does not declare that integration complete. No public schema migration, new
producer effect path or relaxed Core transition is introduced.

## Integration acceptance

In addition to the original 11 owner tests, execute actual child processes
that terminate before proof, after proof commit but before disposition, and
after disposition. Reopen the persisted stores in new processes, reconstitute
the exact reviewed snapshot through the native decoder, and invoke the same
recovery owner. Assert original receipts, original intent, full Transport rows
and bytes, single Attempt and empty Result set remain unchanged; exactly one
proof and NOT_SUBMITTED emerge. Further fresh-process replay must preserve both
store hashes and make zero driver/submission/child calls. These synthetic
staging fixtures exercise real local SQLite/process/guard behavior; they do
not establish new target qualification or scientific execution evidence.

The dedicated recovery route owns both the Execution module and fixed
Controller ingress and conservatively selects existing Execution safety tests
plus the native Transport package. It does not weaken selector self-protection:
route/config changes retain the existing full-validation trigger. Locally run
focused recovery/process/selector and necessary adjacent checks. Before merge,
the integrator must bind a clean committed candidate to authoritative selection
and all required CI/full evidence under the existing policy, with independent
L3 review. No local test substitutes for required CI.

Retain the original failed test-selection log alongside its corrected selector
run, all prior source hashes, original-store backups and actual recovery/child
submission evidence. Exact unchanged runtime source may reuse that historical
evidence after independent source/claim review; source changes require an
affected-claim reassessment. Do not launch new chemistry merely to refresh
unchanged evidence. Runtime qualification, deployment and new Study execution
are separate boundaries.
