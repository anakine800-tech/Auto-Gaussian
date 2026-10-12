# Auto-G16 study stage session boundary

Status: DRAFT for independent review. This narrows section 4 of
[direct-study-execution.md](direct-study-execution.md). It freezes no preparation,
observation, approval-issuance or scientific-acceptance capability by implication.
The four-part Owner authorization covers implementation after this exact review.

## Existing boundary and proposed composition

The existing fixed Controller validates three approvals, code inventory,
snapshot, current profile, store identities and publisher qualification. Keep
those comparisons and `execute_once` unchanged. A process must not rewrite the
legacy `_FIXED_*` bindings to move between stages. Add a separate owner-scoped
session registration, with original fixed pilot behavior remaining the fallback
only when no study session exists. Coexisting fixed and study installations
reject; never choose one silently.

The new private Execution owner is `auto_g16.execution._study_stage_session`.
It selects only a prepared stage already published by the Study runtime owner.
No public constructor accepts a driver, callback, port or snapshot object.
Its proposed external entry is `open_prepared_stage(study_id, stage)`, as narrowed
by runtime §2: canonical UUID and first-slice stage=xtb only. It internally
loads the qualified registration and acquires the exclusive Study lock on
runtime/initialization/. A caller cannot supply an already-held capability,
path, store or installation. References below to a runtime capability mean the
private session state minted INSIDE that entry, not an external parameter.
The other five stage names remain future extensions requiring their own exact
predecessor contracts. Runtime §4 local-uninstalled initialization is insufficient
to open this session; the installation loader remains DRAFT and unavailable.

One session is active per process, guarded by a nonblocking process lock as well
as a ContextVar. Nested or concurrent opens, PID change after fork, a different
Study or stage, or a changed stage publication fail closed. The session token
is private and cannot be provided by CLI/HTTP. Resetting the context on exit
does not authorize a subsequent stage: a new open repeats all native validation.
Existing native per-Attempt completion guards remain required.

## Prepared-stage document

The runtime owner publishes canonical immutable bytes named by the stage's
prepared-operation receipt, never discovers a latest file. Closed schema
`auto-g16-study-prepared-stage/1` has exactly:

`schema, study_id, request_sha256, stage, attempt_id, snapshot_id,
preparation_receipt_id, installation_id, source_commit, source_tree,
files, databases, code_files, scientific_approval_id,
batch_submit_approval_id, operational_confirmation_id`.

The first slice accepts xtb only; the other five compute stages and local
thermo/population stages reject until their separate extension is frozen.
IDs must match the /2 reserved Attempt and runtime's native materialization.
source_commit/tree are exact 40-hex identities from the installed source archive.
Approval IDs are the three exact existing native records; no booleans, approval
payloads or approval issuance occur in this owner.

`files` has exactly profile, snapshot, input, pbs, basis, qualification,
reviewed_semantics, evidence. The first seven values are exact native
`_PublisherFileBinding` serializations
{path,parent_chain,file_identity,sha256,size_bytes}; evidence is a duplicate-free
bounded array of those bindings. Every file is below the installed runtime or
immutable source roots already bound by the runtime capability. Paths are not
independently supplied through the command line. Apply native full ancestor,
no-follow, one-link and size/hash checks; content pins remain held to exit.
Use native per-file caps (basis/review 64 KiB, qualification 1 MiB, other stage
inputs 16 MiB); evidence remains bounded by existing publisher readers.

databases is exactly core,approval,transport,journal; each has
{path,parent_chain,file_identity}. These must equal the runtime capability's
four bound stores; no snapshot-supplied alternative or creation fallback.
Open existing files only after no-follow checks. Use native existing-store
owners and validate the actual connected database path before any effect.
code_files is the exact native Controller Python inventory plus this session
owner and the runtime capability owner. The installed source manifest is pinned
and verified as data separately, not counted as a loaded Python module. It must bind
actual loaded paths under the qualified source archive, not caller-named
copies, an editable worktree or a matching version label.

Restore profile through the native closed profile decoder and snapshot through
the native snapshot decoder. Check current Core, Project creation/association
proof, exact input hash, scheduler bytes, same request/Attempt and original
preparation receipt. Construct the existing native fixed-run and publisher
installation objects internally; they are session contents, never assigned to
the legacy globals. `_FixedPilotRun.stores` retains its exact three roles
Core/Approval/Transport; the Project journal is held separately by the session,
never added as a fourth run store or used to relax `_assert_store_bindings`.
Native source, qualification, code and original approval
checks must all finish before exposing a callable capability.

CREST and Gaussian predecessors are restored only through their native source
and handoff owners. This document does not invent their registration shapes.
Their exact preparation/source document contract must be reviewed before those
stages can open. Unsupported or missing predecessor registration rejects before
driver creation; xTB-only implementation is not a completed six-stage runner.

## Native owner selectors and execution

Add narrowly owned selectors for the active Controller run and Transport
publisher installation. With no session they return the existing fixed values.
With a session they require the private current token, original PID, held
process/Study locks, pinned document and exact object identity. They reject any
non-null legacy fixed value. Deployment `assert_identity` and Controller
current-authority checks use these selectors; never remove the identity check.
The four required integrations are Controller `_fixed_pilot_context` run
selection and `_load_current_authorities` identity check, and Transport
`_read_publisher_deployment_identity` installation selection and
`_PublisherDeploymentRead.assert_identity` installation identity check.
The original `_fixed_pilot_context` continues to own code pins and all current
approval rechecks. Its inventory gains session source files only in the new
session path; old pilot inventory/grammar remains unchanged.

The yielded capability has only `submit_once` for this first exact surface.
At the beginning of every call it verifies that its captured session object
and token are exactly the current object/token, its original PID is unchanged,
the session is not closed and both Study/process locks remain held. It then
atomically consumes its one call while holding the process guard. A capability
retained after its context closes, including one called inside a later session,
must reject before driver construction or a Core claim; checking only the
currently selected session downstream is insufficient.
Calling it invokes the existing `_run_first_publisher_pilot`, including its
native Gaussian claimed-phase approval callback and `execute_once` WINNER
claim. No injected callback, direct Transport call or duplicated claim logic.
Once invoked, it cannot invoke again; repeated Study commands use native
receipt recovery and cannot re-enter a submission. A failure before return
does not reset consumption. The sole Core claim remains the durable boundary.

Collection/reconciliation/session preparation require their own exact capability
extension; do not expose the broad existing port on the yielded object. Context
exit revalidates all source/store names and pins, then closes native handles
and resets process/context guards even after exceptions. A post-effect exit
validation failure preserves all native Core/Transport facts, including an
already-recorded SUBMITTED or terminal state. Study records an unresolved
`exit-validation-failed` stop and never downgrades Core to UNKNOWN, fabricates
a second submission outcome, or retries. Only native reconciliation can resolve
the uncertain part of the operation acknowledgement.

## Validation and deployment

Offline tests use the actual Controller, Approval/Core stores and session
selectors with only the final mechanical peer synthetic. Prove normal fixed
pilot compatibility; one successful claim; repeated call/process restart never
submits twice; failure before/after the claim; expiry/revocation at native
checkpoints; changed request/stage/snapshot/store/source/loaded path; missing
handoff; dual fixed/session installation; nested and concurrent process opens;
forked token; closed-session use and an A capability called in B's session;
pin mutation on exit; exceptions release guards. Verify recorded
submission count and immutable prior rows, not merely mocked method counts.

Preserve real subprocess crash evidence and run the applicable native target
qualification before merge/activation of this production-reachable surface.
Local tests, the old task-local launchers and PR #201 do not qualify this new
session owner. No server writes or new computation are authorized by a test.
