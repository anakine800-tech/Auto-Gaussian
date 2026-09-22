# Auto-G16 same-Attempt collection recovery — frozen C2 design

Status: **C2 DESIGN FROZEN; BOUNDED IMPLEMENTATION AUTHORIZED**.
Accepted design bytes: SHA256
`e1201350faecea03bee20e4ab2a3a92bd8d5bdea4385655f31507338b110b70b`
(29507 bytes). Independent exact-delta PASS: SHA256
`f6492ccec61d268f8aa9ea66b615c1878348124fb98d31dc510bc932c559bfbf`.
The coordinating task recorded delegated technical acceptance on 2026-09-16.
These status annotations are a mechanical delta from the retained exact C2
design; the design hash above does not describe these annotated file bytes.
Task: `V31-SAME-ATTEMPT-COLLECT-RECOVERY-01`.
Classification: v3 feature development; OWNER-GUIDED until exact contract
acceptance, then bounded implementation within this contract; L3 boundary.
This document proposes the smallest private recovery delta. It does not activate
a deployment, change an existing approval, or authorize product implementation
before the coordinating task records acceptance of these exact bytes.

## 1. Authority, baseline and outcome

Authority remains AGENTS → OWNER_DECISIONS → boundary-spec → acceptance →
context-map → AUTONOMOUS_DEVELOPMENT → current explicit Owner Gate. The
development handbook supplies operation order. This is not a BUS-managed task.
The coordinating Owner task has authorized a sequential contract, isolated
implementation, incremental validation/independent review, same-job native
acceptance, and final integration proposal. Publication and integration are
outside this task's present authority.

The App-created linked worktree initially held clean detached
`6b2ece4443951381f0206c93e55e581ca175dd5e`, tree
`b73933008a2560a3b6f4e093bac26611e4b187de`. It is an ancestor of the accepted R4
dependency, with 0 base-only and 13 R4-only commits. A unique
`codex/v31-same-attempt-collect-recovery-01` branch was created and fast-forwarded
to `8d49ef23e7c74c4333c551e81461e3f0921948ab`, tree
`6141c8ef3764fa54d1b5705bc303b8c9f6abc0c9`. No merge commit, cherry-pick,
shared-main change, original R4 worktree change or product edit was needed.
Post-binding require-clean and JSON preflight both pass all seven checks.

Outcome: explicitly reopen the same already submitted xTB receipt-mode Attempt
in a new process, recover its exact native snapshot and durable authority,
collect once through the existing native collector under a separately reviewed
bounded continuation, persist native evidence/assessment/Result, advance Core
only through its existing service, and recover partial local persistence by
idempotent local replay. No new calculation is needed.

Non-goals: fresh submission, UNKNOWN submission reconciliation, recovery child,
new Attempt, provisioning, allocation, staging, qsub, qdel, remote writes or
cleanup; new scientific settings, new Q, source/wrapper upgrade, CREST, Gaussian,
strict-mode migration, public API/schema expansion, daemon, lease service,
automatic retries, general authorization platform, PR/push/merge/release.

## 2. Verified gap and unchanged evidence

R4 `program.py` production `prepare()` requires PLANNED for receipt mode.
`_validate_program_review_semantics()` is a pure mapping validator; its temporary
snapshot is not an exposed restoration authority. R4's Controller requires a
live in-process snapshot. `_PublisherDeploymentRead.assert_current()` checks the
old pilot window at driver/evaluation boundaries. An expired original window
therefore cannot be bypassed by restarting the old launcher.

The actual pilot has one submitted Attempt, one submission intent/outcome and
one job. The local read-only inventory on 2026-09-16 found Core SUBMITTED,
180 Observations and zero Results; Approval has three evidence records,
Transport one runtime attestation, and Project journal one binding/intent.
The exact private IDs, paths, physical identities and file hashes are retained
in the external review packet, not embedded in this public candidate.

External independent acceptance establishes the same xTB job exited zero,
converged and yielded stable bound output. It is neither native capture nor
Core success. The original approval/window, UNKNOWN completion history, original
raw files, wrapper/Q/probe evidence, and external acceptance remain immutable.
Do not rerun qualification, FC06, or the scientific program to fill this gap.

## 3. Submitted-snapshot restoration owner

Add a private `restore_for_collection` entry to the existing Execution-owned
snapshot service. Keep `prepare()` and its PLANNED guard unchanged. Restoration
returns the existing public `ProgramExecutionSnapshot` type with identical
semantic payload, scheduler bytes, snapshot ID and effect intent ID; it is not
a new snapshot or a third public execution record.

The owner may extract a shared *pure* decoder from the current review-semantics
validator. The public-facing validation behavior still returns a closed mapping
and has no side effects. Only the newly reviewed service calls that decoder for
restoration and completes the additional checks below. A Controller cannot
capture a validator temporary, call `_from_verified` itself, use `object.__new__`,
patch state to PLANNED, choose synthetic privileges, or accept a duck-typed
snapshot. Implementation-private construction inside the owning decoder/service
is subject to the same full identity reconstruction tests.

Zero wire applies from process start: restoration, fixed deployment and exact
driver construction, qualification checks, predecessor closure and the local
replay eligibility check must all be local. Select terminal/existing-complete-
bundle replay before any remote initialization or observation. The private
fixed-collection factory must meet this requirement without a new driver class,
caller bypass flag or weakening of the original submission path.

Restoration requires all of the following before returning a usable collection
context, without provisioning, current-Project network attestation, or writing
any of the original four databases during the precheck:

1. The fixed reviewed installation supplies the exact original Core, Approval,
   Transport and production Project journal locations. Reopen existing only;
   validate full no-follow parent chains, regular-file device/inode and connected
   database paths before constructors that can create or initialize a database.
   Missing, copied, replaced, aliased, linked, cross-store or wrong-generation
   databases fail closed. Keep default SQLite durability and the existing
   qualified trusted-namespace limitation; do not claim descriptor-bound SQLite.
2. Reclose canonical original expanded snapshot bytes against the original
   persisted Operational Confirmation semantics and installed original snapshot,
   input, PBS, profile and resource records. Every nested closed shape, version,
   semantic ID, profile/config/runtime identity and rendered byte must agree.
   No current default, mutable profile refresh, new timestamp or latest-source
   substitution participates in original identity.
3. Core Attempt → Task → WorkflowRun → Project and plan/revision/resource must
   agree. The only admitted current states are SUBMITTED, RUNNING, SUCCEEDED,
   FAILED. PLANNED, SUBMISSION_INTENT_RECORDED, UNKNOWN and all other states are
   refused.
   Completion UNKNOWN observations are preserved and do not equal a Core
   submission-UNKNOWN state. The Core intent/outcome must identify the original
   successful submission; this slice does not restore reconciled submissions.
4. Load the original Project binding from the exact production journal and
   reuse its existing binding/intent/evidence validation. Match the snapshot's
   complete binding, original target, Project root and Attempt suffix. The
   approved local workspace anchor and original remote allocation token remain
   unchanged. Current remote no-follow identity is checked by the original
   operation owner at subsequent reads, never invented during local restoration.
5. Under the existing completion guard, reclose the existing runtime attestation,
   Core effect receipts and Transport physical authorities through the existing
   `_load_receipts`, workspace/stage/job reconstruction. Require exactly the
   original successful SUBMIT_QSUB_ONCE predecessor and original job ID. A missing
   side of the dual-source predecessor, conflicting job, raw-only diagnostic,
   foreign snapshot/intent, or changed history refuses collection.

Controller owns approval semantics. It reloads and checks the original
Scientific Approval against the exact plan/displayed meaning, APPROVED Batch
and exact membership, and current APPROVED Operational Confirmation against the
restored snapshot. Use submitted-phase checks, never call the PLANNED-only
`validate_effect_authority()` on a submitted Attempt or loosen that validator.
Transport does not receive Core/Approval objects, human decision flags or
approval callbacks. Restoration alone gives no execution/claim authority.

## 4. One separate collect-only continuation

The original three approvals, original deployment basis, Q, source identity and
pilot window stay byte-identical. A new fixed, create-new local installation
attachment records only the additional same-Attempt collection scope. It is
review material under the existing deployment/Owner trust model, not a fourth
public Approval record, independent authority service, self-signed permission,
revocation log or transferable capability.

Proposed private canonical schema `auto-g16-v31-collection-continuation/1` has
exactly these fields, with no unknown keys or executable content:

| Field | Closed meaning |
| --- | --- |
| `schema` | Literal schema above. |
| `original` | Exact `attempt_id`, `snapshot_id`, `effect_intent_id`, `job_id`, `project_physical_binding_id`, `resolved_server_profile_id`, `original_basis_sha256`, `snapshot_semantics_sha256`, and the three original approval IDs. |
| `stores` | Ordered roles core/approval/transport/project-journal; each exact canonical absolute `path`, root-to-parent `parent_chain`, `file_identity`; Transport additionally original store/instance/runtime-attestation IDs, journal original journal identity. No invented Core/Approval store UUID. |
| `collector_source` | Exact new `commit`, `tree`, and finite ordered actual-module `files` with repository-relative path, SHA256 and size. Actual installed paths/chains/inodes are separately pinned by the reviewed installer. |
| `original_source` | Original reviewed commit/tree, wrapper SHA256/size and Q file/payload SHA256. These describe publication, not new collector qualification. |
| `window` | Explicit UTC `started_at`, `finished_at`; six-digit microseconds and Z, ordered, no default duration or automatic extension. |
| `scope` | Exact action `collect-existing-job`, `maximum_remote_epochs=1`, permitted operations QUERY_SCHEDULER/STAT_EXACT_FILE/FETCH_EXACT_FILE, exact receipt and declared output names, `local_replay=true`. |
| `review_evidence` | Exact digests/sizes of retained Owner continuation decision and independent accepted source/compatibility review; original bytes and a separately reviewed closed semantic projection are pinned by installation. |

Reuse R3 canonical types/bounds for digests, source IDs, timestamps and physical
nodes. Bound this attachment to 1 MiB, at most 256 code entries and exactly four
store roles; no wildcard paths or discovery. Its canonical SHA256 is the
continuation identity; it has no self-hash field. The actual approved content,
new window and physical installation inventory are prepared after implementation
review, then submitted to the coordinating task's technical approval. This draft
does not invent those operational values or require the user to repeat the
already granted same-job scope.

The locator comes only from the newly reviewed fixed deployment entry, never
CLI/environment, caller JSON, Q/profile contents, a latest-file search, or an
`approved` boolean. Controller compares the original decision plus reviewed scope
to every field and original authority. Driver sees only mechanical fixed-file
identity/scope, never interprets human approval. Recheck installed bytes, code,
current profile, stores and current window at the relevant effect/write boundary.

The new source is permitted only to decode and collect the old publication tuple.
It must reconstruct the exact original scheduler/3, material/2, prebinding/3,
wrapper and receipt expectations. Original Q's implementation commit/tree still
matches the original basis; it is never rewritten to the new collector commit.
Acceptance of new collector code is a separate exact compatibility review; old
P08/CI is supporting history, not qualification of the new code. If wrapper,
receipt grammar, manifest, scientific invocation, profile or source pairing must
change, stop this task instead of reinterpreting the original job.

## 5. Read-only driver path and native collection

Add a private fixed-collection factory/path for the existing exact production
driver. Its normal constructor/submission path retains all old checks including
the old pilot window. The collection path reuses the original basis/Q/pins,
profile/ProxyJump/bootstrap/runtime checks and predecessor validation; only its
action-time scope comes from the independently installed continuation's window.
There is no `ignore_expiry`, general caller mode switch or fallback from an
expired original deployment. Distinguish historical identity verification from
current collection authorization explicitly in code.

The collection driver refuses ALLOCATE_WORKSPACE, STAGE_EXACT_FILE,
SUBMIT_QSUB_ONCE and RECONCILE_SUBMISSION before any wire call, including direct
private operation invocation. Runtime and Controller also never construct an
execution port, call `execute_once`, claim submission or provision an Attempt
on this path. Keep all seven operation schemas, four-key runtime qualification,
transport store DDL and exact production-driver checks intact.

Within one guarded invocation: revalidate → non-mutating local replay check → if no complete
durable bundle and remote epoch is unconsumed, persist the continuation start
audit → original `_collect_program_completion` → original capture/Result reread →
assessment → Core transition → idempotent local replay. A complete durable bundle
is replayed without remote recollection. Existing terminal state uses replay
only; no terminal-to-terminal replacement is allowed. The eligibility check
inspects and validates existing durable records without appending observations
or results. Call the write-capable original replay only when a complete usable
native bundle is established; do not call it to discover whether a bundle exists,
since its missing-bundle branch can append acquisition-unknown. A terminal state
without its complete valid native bundle is a rejection, not a new collection.

The audit is a private closed payload in the existing append-only Core
Observation mechanism, not new DDL or a new Core lifecycle state. Its `data`
mapping has exactly these eight fields:

| Field | Exact value |
| --- | --- |
| `schema` | `auto-g16-v31-collection-start/1` |
| `continuation_sha256` | Ordinary SHA256 of the pinned canonical continuation bytes. |
| `attempt_id` | Original Attempt ID; equal to the Observation's Attempt ID. |
| `program_execution_snapshot_id` | Original restored snapshot ID. |
| `effect_intent_id` | Original submission intent ID. |
| `job_id` | Original successful submission's exact job ID. |
| `collector_source_sha256` | Existing `semantic_sha256` of the continuation's complete closed `collector_source` mapping. |
| `observation_prefix_sha256` | Unchanged `_observation_prefix` of every Observation strictly before this audit. |

Use `observation_type="auto-g16-v31-collection-start/1"` and the existing
`semantic_id("program-collection-continuation-start", data)` rule for
`observation_id`. Reclose exact field types/values, source/continuation bindings,
ID and the actual preceding prefix when reading history. The unchanged full
`_observation_prefix` includes this audit in all later prefixes. Original
`effect_sequence` and assessment `evidence_observation_ids` still include only
native effect receipts. Never filter the audit from a digest, reinterpret it as
a receipt, recompute an old assessment prefix, or alter the receipt algorithm.
Malformed, duplicate, conflicting, inserted or reordered audit/history fails
closed; at most one audit may bind a given continuation digest, irrespective of
whether another supplied ID or prefix would otherwise be self-consistent.

Append only after the non-mutating check establishes that a new remote epoch is
needed, under the existing guard and before the first remote operation. Do not
append an audit for terminal replay or an already complete durable bundle.
Exact existing audit means this continuation cannot begin a second remote epoch,
even if no remote receipt followed the audit. If the audit write or remote result is uncertain, preserve
it and stop; never infer that no call occurred. Explicit local replay can still
finish durable work. A further remote epoch, if needed, requires a new finite
reviewed continuation under the already authorized same-job scope.

The continuation's receipt/output name list must equal the complete original
snapshot declaration order: receipt metadata, all required outputs and all
optional outputs. Reject omission, duplication, reordering, extra names or any
caller-selected subset. The epoch uses these original declarations, opening and closing exact
job absence, STAT/FETCH/restat, existing no-follow identities and size/hash
limits. The upper wire-call count is two queries plus three operations per
declared receipt/output member (less for absent files). Active/unknown scheduler
evidence, missing receipt or identity conflict retains existing UNKNOWN/failure
semantics. No success is inferred from absence. No external diagnostic file,
download or acceptance JSON is inserted as a native capture.

## 6. Concurrency, crash and replay

Reuse the version-2 Transport store's nonblocking parent-directory guard and
existing process/fork/token protections. Hold one owner across final four-store
binding checks, start audit, collector, Result reread, assessment and transition.
A competing process/thread/handle makes zero remote calls or epoch writes. No
new lock file, TTL, lease, custom VFS or database-inode flock is introduced.

Every mutation uses existing owning APIs; no direct UPDATE, state repair SQL,
cross-store transaction fiction, copy/import of live databases, rollback or
deletion. A database content digest is audit metadata at a named observation,
not an immutable runtime identity: legitimate native appends change it. Retain
physical identities, schemas, instance identities and semantic predecessors.
Approval and Project journal records remain read-only throughout collection.

On restart, explicitly reopen and validate again. Before a complete bundle,
partial native observations remain partial and cannot promote; the consumed
epoch is not retried automatically. After bundle persistence, replay revalidates
its complete raw/physical/prefix evidence and appends only missing assessment
or Core transition. After assessment persistence but before transition, replay
uses the same assessment. After completion, replay returns the same durable IDs
and leaves counts/state unchanged. Contradictory history refuses promotion.
Zero-wire counters cover the actual wire/effect-owner boundary from process
start through restore, driver/qualification construction, predecessor checks and
the entire replay. A missing/invalid bundle is not a reason to create an UNKNOWN
assessment during the eligibility check. Preserve the original terminal replay
fast path: no appended audit or extra assessment may disturb `observations[-1]`
being the existing latest assessment.

Replaying a partial operation to *write* an assessment/transition still requires
the current continuation window and exact deployed collector. Expiry stops new
remote reads and local promotion; prior effects/evidence remain. Pure historical
readback of an already persisted result/state is allowed after expiry but must
not issue fresh success authority or claim a new in-window assessment. No clock
patch or retrospective extension is permitted in production.

## 7. Allowed files and reuse decisions

Current C2 authoring changes only this document. After exact freeze, the following
bounded set is proposed; a new path or boundary requires a reviewed contract
delta before editing it.

| Files | Disposition / reason |
| --- | --- |
| `auto_g16/execution/program.py` | EXTRACT pure decoder; WRAP it with reviewed collection restoration. Preserve prepare/public record meanings. |
| `auto_g16/execution/program_runtime.py` | WRAP existing predecessor/collector/replay and add continuation audit/checkpoints. No new reducer or capture format. |
| `auto_g16/transport/_program_rtwin.py` | EXTRACT original mechanical identity checks from temporal scope; WRAP fixed read-only continuation path in exact driver. |
| `scripts/run_v31_publisher_pilot.py` | WRAP/add private restoration/collection entry and existing-only four-store reopening; retain first-submit entry/default behavior. |
| `tests/v31/transport/test_publisher_collection_recovery.py` | New focused synthetic and actual-process offline recovery vectors below. |
| `tests/v31/transport/test_publisher_pilot_orchestration.py`, `test_program_completion.py`, `test_rtwin_successor_bridge.py`, `test_program_composition.py` | Only directly affected compatibility/adversarial assertions. |
| `OWNER_DECISIONS.md`, `docs/v3/boundary-spec.md`, `docs/v3/acceptance.md`, `docs/v3/AUTONOMOUS_DEVELOPMENT.md`, `config/context-map.toml`, `docs/v3/STATUS.md`, this document | Append exact accepted delta/current status; retain historical authority/evidence. |

PORT unchanged: native collector/reducer, completion capture, C4 guard, Project
journal binding loader, store reopen APIs, approval models and original Q/probes.
No REWRITE is justified. In particular no changes are proposed to Core/Approval/
Result public modules, project_provisioning.py, transport/program.py, _driver.py,
completion wrapper/pure receipt grammar, selectors, workflows, installed Skills
or historical golden vectors. Reopening/pinning wrappers belong to Controller.
If a protected API cannot support the promised precheck or ownership semantics,
report the concrete interface gap for independent review instead of broadening.

## 8. Incremental acceptance and validation

| ID | Required new evidence |
| --- | --- |
| CR01 | Real process A exits with synthetic submitted durable state; independent process B restores the identical snapshot and native completion through approved offline seams. No real SSH/program and no validator temporary extraction. |
| CR02 | SUBMITTED/RUNNING/terminal admission; PLANNED, submission UNKNOWN, reconciled submission, missing intent, wrong generation and mismatched approval reject before collection. Original prepare still refuses consumed Attempt. |
| CR03 | Original expired window refuses old path; exact new window permits only collection; early/expired/malformed/drifted continuation refuses. Original approval/basis/Q bytes unchanged. |
| CR04 | Same bytes at new inode, ancestor replacement, swapped/copied stores, wrong store instance/journal binding/receipt, changed profile/snapshot/input/PBS/approval/source all fail closed. No create-on-missing. |
| CR05 | Every forbidden operation/execute/claim/provision seam has tripwire/counter and remains zero; only one job/Attempt/submission exists before and after. Source/Q original tuple matches and unknown/mixed versions reject. |
| CR06 | Native Mac default SQLite plus actual directory flock: two processes, threads and separate handles contend; only one epoch audit/collector; loser has zero remote calls/writes. Reuse unchanged C4 guard evidence; exercise new context's lock lifetime. |
| CR07 | Crash before/after start audit, after remote effect before receipt persistence, before/after Result append/reread, assessment append and transition. Explicit fresh-process replay neither duplicates nor restarts remote collection. An exact audit with no following receipt consumes its epoch. Validate exact audit payload/ID and unchanged full-prefix/receipt-only sequence rules; malformed, duplicate, altered, inserted or reordered audit rejects without repairing historical prefixes. Incomplete epoch remains incomplete. |
| CR08 | Complete bundle → missing assessment → missing transition → terminal replay produces same Result/capture/assessment identities. Actual wire/effect counters from process start through restore, driver/qualification construction, predecessor closure and replay stay zero. No audit for complete-bundle/terminal replay, no missing-bundle probe UNKNOWN, no extra assessment and terminal counts/state unchanged. Corruption/contradiction cannot promote. |
| CR09 | Existing first-submit R4, strict/V30 boundaries, original xTB source/material/snapshot goldens and collection classifications remain unchanged in affected tests. No FC06/full/P01–P08 repetition without a named new gap. |
| CR10 | After reviewed exact installation: same previously submitted real job undergoes native collection, capture/Result persistence, Core reduction and fresh-process replay; original four-store lineage and one-submission count remain intact. This is a separate operational gate. |

Start with document syntax/link/identity/diff checks and CI-contract static audit.
After implementation use the named focused new tests plus the smallest affected
existing methods; actual-process tests use inert synthetic fixtures in external
scratch. Record command, interpreter/OS/SQLite/mount, exact source tree/diff hash,
start/finish, exit, count/skips and limitations. Freeze once for independent
findings-first review. Record exact R4-base/new-head selector output separately
from the eventual main-base integration diff. A conservative legacy-release
selection is reported, not bypassed; it does not authorize a full run in this
incremental task. Missing/unmapped routes stop before tests. Old CI/full results
do not transfer to new source.

## 9. Operational packet and final handoff

Before any actual installation or native collection, produce a concrete packet
for the coordinating technical reviewer: exact accepted contract/code identities,
independent review, original four-store physical/semantic inventory, original
approvals/basis/Q/input/PBS/snapshot, new fixed code/continuation/entrypoint files,
create-new destination/physical installation plan, explicit current UTC window,
one exact job/Attempt, finite QUERY/STAT/FETCH budget, local append set, success/
stop criteria and retained evidence paths. Review source import paths as well as
file hashes so the new code cannot silently import the old installation. Bind
the full actual project-module import inventory, not just edited files (the
original reviewed launcher binds 65 imported files). At install/reopen verify
actual module paths and source bytes against that exact candidate, with approved
interpreter/import configuration; runtime discovery cannot approve extra code.

Install only new local reviewed recovery artifacts; preserve the old installation
and launchers. No modification/deployment of remote publisher/runtime or remote
files. Read original job root only through native operations and pin the approved
target/root/Attempt. Hash and read back original stores and immutable evidence
before/after; inspect audit/receipt/capture/Result/assessment/state with owning
services. Confirm fresh-process local replay, zero new qsub/Attempt, and exact
unchanged approval/Project journal/history. A failed boundary stops with retained
evidence and no cleanup, scientific rerun or automatic retry.

Final matrix must separate base file-completion FC01–FC15 and C4-01–09, accepted
R4 publisher source, target qualification/installation/external smoke, and CR01–10
new recovery. Mark historical missing samples NOT_ACQUIRED and each unrun new
cell NOT_RUN. CREST remains separate. Report exact dependency/integration options
and current PR identity only when inspected; neither this draft nor the eventual
matrix publishes/updates a PR or grants integration authority.

Current gate: bounded implementation and CR01–09 evidence, then independent
candidate review. Real-store writes, native collection, a new operational
window and deployment remain behind the coordinating task's concrete CR10 packet.

## 10. Independent checklist trace

The coordinating task supplied the one-page independent pre-review checklist
SHA256 `430fc20b4da5df2f39591b219cc802c7d28b290eb6f8de20af76d16e381ffaa8`.
Its six requirements map to sections 5/6 (remote read-only/native writes), 3
(Execution restoration), 4/7/9 (old-Q/new-source separation), 4 (separate
window), 3/5 (native predecessor/epoch closure), and 8/9 (incremental and real
acceptance). No pending-file acquisition or historical process-ID gate is added.
Changing four existing private modules is proposed because they already own
snapshot construction, collector checkpoints, fixed driver authority and
Controller composition. Duplicating them merely to keep six historical files
unchanged would create two safety implementations; the original wrapper and
receipt grammar instead remain byte-identical and the accepted new delta is
separately reviewed and pinned.

C2 incorporates only the two P2 clarifications in independent C1 review SHA256
`5a8df5c15b5da58ab0961eb06b7984e77188565ec84c7ea801fdedf314a45909`:
exact audit/prefix/replay compatibility and end-to-end zero-wire replay, including
strict receipt/output scope equality. The corrected C1 baseline SHA256 is
`261e15f7173e93f83d9874bba61742e1d18651e21ffb704ed79b65d7c879c907`.
No allowed path, source ownership, operational scope or validation level expands.

## 11. TP01–TP06 asynchronous transfer-progress delta

On 2026-09-22 the Owner directed that recovery of the same Attempt use progress
evidence or resumable chunks and must not be interrupted merely because a fetch
is quiet. The accepted minimum delta is progress evidence; it does not add a
chunk protocol or any remote operation.

| ID | Frozen requirement |
| --- | --- |
| TP01 | Only a collection-owned `FETCH_EXACT_FILE` starts progress reporting. Submission, reconciliation, ordinary transport and non-fetch collection calls emit none. |
| TP02 | Progress runs outside the transport I/O/deadline thread. A slow, blocked or failed reporter cannot delay, time out, cancel or otherwise change the fetch. |
| TP03 | Events expose only operation, phase, elapsed milliseconds and, after the driver returns, bounded channel/result facts. They contain no path, content, credential, host, approval or scientific data. |
| TP04 | A waiting heartbeat is diagnostic only. Elapsed time or reporter failure is never completion or failure authority. Existing complete frame, EOF, token, size, SHA-256, restat and scheduler/receipt checks remain unchanged. |
| TP05 | Interruption or the existing absolute timeout remains `UNKNOWN`; partial bytes are never captured. No qsub, new Attempt, retry, qdel, cleanup, remote write or replacement path is introduced. |
| TP06 | Focused tests prove the reporter is asynchronous, is selected only for collection-owned fetch, and cannot change the returned transport tuple. Reuse CR01–CR09 evidence unless this delta changes the covered bytes. |

This delta changes only the already allowed private
`auto_g16/transport/_program_rtwin.py`, its already allowed affected test
`tests/v31/transport/test_rtwin_successor_bridge.py`, and the authority/status
documents listed in section 7. `_driver.py`, operation schemas, timeout values,
wire frames, receipts, stores and public records remain byte and meaning
unchanged. CR10 still requires a fresh exact collector-source binding,
independent review and one collect-only operational packet for the original job.

## 12. IR01–IR08 interrupted-prefix recovery delta

The 2026-09-22 native collection exposed a narrower crash boundary than C2
closed: an exact present-file `STAT_EXACT_FILE` receipt can persist before its
paired `FETCH_EXACT_FILE` returns. Later collection processes must not discard
that predecessor and start a fresh file sequence. The Owner directed continued
same-Attempt collection with progress evidence or resumable transfer, without a
new calculation, submission or Attempt. The following exact delta closes only
that interrupted prefix.

| ID | Frozen requirement |
| --- | --- |
| IR01 | Before opening a new scheduler-absence epoch, a new reviewed continuation detects at most one latest successful present-file STAT whose observation ID has no successful FETCH consumer. Zero or one is accepted; multiple, malformed, absent-file, foreign-job or conflicting candidates fail closed. |
| IR02 | The repair issues only the exact FETCH request already derivable from that persisted STAT, through the existing collection-owned driver and its TP01–TP06 progress reporter. It does not STAT again, choose a file, change a token/size, or create synthetic bytes. |
| IR03 | The completed repair persists the ordinary physical effect and Core FETCH receipt. Its returned bytes are discarded; the abandoned epoch remains non-authoritative and cannot become a completion bundle. |
| IR04 | After the repair, the existing collector opens one new exact scheduler-absence epoch and performs the complete declared receipt/output capture from the beginning. The new bundle may use only evidence after that new opening and retains existing STAT/FETCH/restat/final-absence validation. |
| IR05 | Each remote repair/capture attempt requires a fresh, exact, unconsumed continuation and one finite window. A consumed continuation, timeout, interruption or ambiguous fetch grants no automatic retry; a later remote attempt requires another reviewed continuation. |
| IR06 | Recovery never deletes, replaces or edits the abandoned observations. Collection audits and UNKNOWN assessments remain append-only history. No qsub, new Attempt, qdel, cleanup, remote write or scientific execution is added. |
| IR07 | Focused tests cover a process stopping after present STAT, exact restart FETCH selection, duplicate/conflicting/unowned prefixes, failure before the repair receipt, a clean new epoch after repair, and zero-wire replay after a complete bundle. Existing TP and CR evidence is reused where bytes and behavior are unchanged. |
| IR08 | The live `706.master` application requires a new exact source/tree and continuation binding, independent review, retained regular-file progress log, and one collect-only operational window. It does not change the status or identity of any earlier run. |

This delta adds only private interrupted-prefix selection and repair in
`auto_g16/execution/program_runtime.py`, focused coverage in
`tests/v31/transport/test_publisher_collection_recovery.py`, and the authority
references named in section 7. It does not change the public schemas, Transport
operation set, wire framing, timeout, receipt shapes, output declarations or
completion reducer.
