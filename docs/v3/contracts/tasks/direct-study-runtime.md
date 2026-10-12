# Auto-G16 xTB runtime and stage-session composition

Status: section 1 independently reviewed and frozen for local Core implementation
on 2026-10-12; sections 2 onward remain DRAFT. No live activation authority.
Within BUTANE-RELIABILITY-UNIFIED-E2E-01 and its four-part continuation. This
subcontract closes the smallest xTB vertical path, not the six-stage Study.
Only this new document is edited by its author. Owner/boundary authority and
[immutable /2 intake](direct-study-fresh.md) remain unchanged. Read-only preflight
passed with the owned dirty-worktree warning; no tests or remote actions ran.

## 1. First independently implementable gap: Core existing-only mutable open

Current `SQLiteRuntimeStore(database)` calls `_connect` then `_initialize_schema`.
An empty unversioned database can therefore become initialized. This constructor
MUST NOT be the runtime recovery opener. Existing `read_snapshot` and
`_open_readonly_existing` remain unchanged; they do not provide mutation authority.

Add exactly one owner entry:

`SQLiteRuntimeStore.open_existing_mutable(database, *, approved_root, expected_file_identity)`

It is a context manager yielding the exact SQLiteRuntimeStore class, for use
only by a caller already holding the Study writer lock. database/approved_root
are absolute canonical local paths; expected_file_identity is exactly two
non-bool integers (device >= 0, inode >= 1) from the runtime creation receipt.
This API grants no approval, remote or submission authority. It cannot create,
migrate, repair, export a disk snapshot, switch journal format or adopt another
file. It does not accept `:memory:`, URIs, query parameters or caller connections.

The caller owns the outer Study writer lock and the approved-root receipt.
This entry validates containment and pins the entire observed chain; it does not
create a second lock protocol or confer authority on an arbitrary root string.

Core owns the following lifecycle, without importing Study or Transport:

1. Walk from filesystem root using held directory descriptors and no-follow
   opens. Prove lexical containment under approved_root, including the root
   itself. Reject noncanonical `.`/`..`, symlinks, non-directory ancestors,
   nonregular target, hardlinks (nlink !=1), wrong expected inode or missing file.
   Hold all ancestor and file descriptors until context exit. Current Core
   `_readonly_database_state` alone is insufficient for full ancestor binding.
2. Require quiescent rollback-format SQLite header and no `-journal`, `-wal`,
   `-shm` companions before open. Reject even empty companions; never remove or
   recover them automatically. Core's own ordinary transaction journal during
   a yielded native write is permitted; it must be absent at idle/close. A
   crash leaving a hot journal is initialization-unresolved at Study level,
   not permission to let a read or this opener perform SQLite recovery.
3. BEFORE any writable SQLite connection, inspect SQLite header and user_version
   using the already-held target descriptor, then validate the existing schema
   and foreign keys through an existing-only mode=ro connection (query_only=ON).
   Reject empty/unversioned/bad-schema files here. Close this startup validation
   connection before creating the mutable connection, recheck the held descriptor,
   every name and sidecar absence. This prevents treating mode=rw itself as a
   no-mutation guarantee: SQLite could otherwise recover a hot journal on its
   first access. No automatic SQLite recovery is in scope.
   Connect only via canonical `Path.as_uri()+"?mode=rw&cache=private"`, uri=True,
   isolation_level=None. No fallback to constructor or mode=rwc. Set row_factory
   and foreign_keys=ON, check it enabled. Set query_only=ON during startup
   validation; opening/validation itself executes no data/schema mutation.
   Check PRAGMA database_list has exactly the expected on-disk main path and
   that the descriptor/name bindings remain exact across SQLite open.
4. Require exact native SCHEMA_VERSION before any initialization path. Call
   `_validate_schema_identity` directly (the existing comparison to the native
   reference schema, including its legitimate temporary in-memory schema);
   require PRAGMA foreign_key_check empty. NEVER call `_initialize_schema` for
   the target. Extra objects, triggers/indexes, partial schema, wrong version,
   broken foreign keys, malformed/zero-byte database or SQLite error reject.
5. Only after all checks set query_only=OFF and yield. The store marks
   `_created_as_memory=False`; `export_memory_snapshot` therefore rejects.
   Bind the held physical guard to this connection. While that connection lives,
   NEVER re-open-and-close another descriptor for the same database inode for
   an attestation: POSIX close may release this process's SQLite fcntl locks.
   Recheck only with fstat on the retained target/ancestor descriptors and
   descriptor-relative stat of names; keep the target FD open until AFTER the
   SQLite connection closes. Do not call `_readonly_database_state` or a second
   Core opener inside `_db`/transaction guards if it opens/closes the same file.
   Any guard validation failure permanently poisons that handle, before raising.
   Restoring a name or removing a sidecar cannot revive it; cleanup/rollback
   still runs, and only a new opener may perform a new complete validation.
   Native `_transaction`
   rechecks the guard before BEGIN IMMEDIATE, before COMMIT and after COMMIT;
   native read access rechecks before use. Do not hold an implicit transaction
   across yield, since owner methods already transact. Caller-side raw SQL is
   not a supported interface and is not authorized by this contract.
6. On normal/exception exit, attest names/inodes/containment, native schema and
   foreign keys, ensure no open transaction, close connection then descriptors.
   Roll back an uncommitted transaction on exception before close. Always
   release resources even when rechecks fail. Successful prior owner commits
   remain facts: an exit failure never rewinds them or changes Attempt state.
   Do not compare database content hash to its pre-write hash on successful
   writes; it is expected to change. Preserve expected file identity throughout.

Use existing RuntimeStoreError subclasses: input/path/open/identity failures are
RuntimeStoreError; schema/version/FK failures RuntimeStoreSchemaError; missing
file may preserve FileNotFoundError for Study not-found mapping. No new recovery
state or automatic retry is introduced. Error messages contain no credentials.
The no-init guarantee includes failure: missing files/directories remain absent,
existing rejected bytes and sidecars remain byte-identical. If a failure occurs
after a permitted owner write, report failure and retain the committed evidence.

Required focused tests: native write/read roundtrip on an existing exact store;
missing/empty/foreign/partial/extra-schema/FK-broken stores; memory/URI/relative/
noncanonical paths; symlink/hardlink/ancestor or terminal replacement; unexpected
sidecars; replacement before transaction/commit; context exception and descriptor
release; query-only validation; `_initialize_schema` tripwire on the target;
no create on missing; rejected-byte hash preservation; disk export refusal.
Preserve existing Core read_snapshot and constructor behavior/tests. This narrow
Core implementation may be independently reviewed before the remaining draft
is frozen; it does not activate run or authorize use against historical stores.

## 2. Fixed installation and owner-loaded session entry

Replace the proposed external capability parameter with:

`open_prepared_stage(study_id: str, stage: str)`

Only canonical UUID study_id and stage=xtb are accepted in this first slice.
The owner loads its installed registration and acquires its own lock/pins;
Study cannot supply a snapshot, object, port, driver, module or callback. It
mints the private session only after native validation. The submitted capability
and selectors obey every identity/use-after-close/atomic-consumption rule in
[stage-session](direct-study-stage-session.md). This is a proposed exact delta
to that draft, not a second externally constructible capability system.

One process-fixed installation, acquired only by reviewed installation startup,
has exactly {schema,installation_id,source_commit,source_tree,source_manifest,
registry_root,runtime_root,creation_root,profile,qualification,evidence}.
schema=`auto-g16-study-runtime-installation/1`. Roots are closed
{path,parent_chain,file_identity}; immutable files are the native
{path,parent_chain,file_identity,sha256,size_bytes} binding. evidence is a
duplicate-free array <=64 of native file bindings. All code runs from the
verified full source archive including `scripts.run_v31_publisher_pilot`;
the auto_g16-only wheel is not sufficient. Qualification and profile are
existing native closed artifacts, not new Study substitutes.

The installed object identity cannot change while loaded. Environment, cwd,
CLI paths, a registry entry and a matching version string cannot replace it.
The production locator is generated by the qualified installer, not assigned
by a task-local launcher. Installation bundle layout is fixed: source/ contains
the exact source archive; installation/study-runtime.json is the one canonical
locator. The versioned loader derives bundle root from its actual loaded module
under source/auto_g16/study/ and reads only that fixed sibling locator through
no-follow descriptors. No search, alternative basename, cwd, PYTHONPATH helper
or --installation override. The locator's closed payload is the installation
object above; a separate qualification/readback receipt binds its complete bytes
and physical root chain along with the source-manifest hash. That receipt is
checked through the already-qualified native installation owner, avoiding a
self-referential manifest hash. The archive manifest binds actual loaded source
files; the locator cannot select code modules, remote roots or profile overrides.

On each production run/authorize/recover-with-effect CLI entry, the versioned
loader verifies this one locator and its owner readback, then internally acquires
the immutable process installation object. No mutable setter is exported;
subsequent loads must return the identical object only after revalidation, and
changed installed bytes require a new process plus separately reviewed
installation. Read-only local /1 and /2 commands do not require or initialize
this installation. Production starts with no acquired binding until reviewed
deployment/readback succeeds. An absent locator is installation-unqualified;
there is no task-local Python bootstrap fallback. Loading
this single fixed locator is distinct from forbidden per-stage `_FIXED_*`
rebinding. Legacy fixed Controller/publisher values and a Study session cannot
coexist. Missing/foreign installation fails before store or remote mutation.

## 3. Private local registry and lock order

This registry is for owner control, not a public frontend DTO. It is one
append-only directory below registry_root. Canonical immutable records have
{schema,sequence,previous_sha256,kind,data}, schema=`auto-g16-study-runtime-registry/1`.
No replacement, deletion, migration, directory scan for latest or duplicate key.
Caps: 64 studies, one xTB prepared-submit entry per Study, 1 MiB per record.

- RUNTIME data exactly {study_id,request_sha256,creation_binding,runtime_binding,
  initialization_receipt_id,installation_id}. Each binding is
  {path,parent_chain,file_identity}; it names a directory, not a database.
- PREPARED data exactly {study_id,request_sha256,stage,attempt_id,
  prepared_document,preparation_receipt_ref,installation_id}. stage=xtb;
  prepared_document is the exact native file binding, not inline runtime code.
  receipt_ref is {kind,id,sha256}; kind=study-xtb-preparation. Validate matching
  runtime receipt and native snapshot/input/approval bindings before accepting.

RUNTIME is published only after initialization is complete. PREPARED follows
RUNTIME and verified preparation/three-approval publication. Future authority
renewal or collection continuations are not silent replacements of PREPARED.
They use existing exact owner continuation records, addressed by identity.

Reader/session lock order: process session guard (nonblocking), registry shared
while selecting the exact immutable entry, release registry, Study exclusive,
Project journal, Core, Approval, Transport guards in native prescribed order.
Then verify entry/runtime/request and all native bindings before minting token.
No registry reacquisition while Study or native locks are held. New records
cannot alter the selected immutable entry; a changed root/file rejects at exit.
Publication entry: process guard, registry exclusive, Study exclusive, native
read guards. It performs no remote effect and cannot be called from an already
locked run step. Recheck complete native facts after acquiring these locks.
A crash between runtime receipt and registry append leaves a local unregistered
runtime; explicit publication can adopt that exact receipt without rerunning it.
Reads never complete publication. No lock stealing or implicit process restart.

## 4. Runtime initialization and four native stores

Immutable /2 creation stays unchanged. Runtime path is deterministically
runtime_root/study_id; creation UUID slots and six initial records remain exact.
No new Attempt/Plan identity or copy of historical results. Use an exclusive
new directory reservation with full pinned ancestor chain and Study writer lock.
Allowed initial children: `initialization/`, `operations/`, `prepared/`,
`artifacts/`, `reviews/`, `public/`, `core.sqlite3`, `approval.sqlite3`,
`transport.sqlite3`, `project-journal.sqlite3`. No arbitrary loader files.

First append initialization intent {schema,study_id,request_sha256,
creation_core_sha256,creation_binding,installation_id,expected_store_names,
expected_records}; schema=auto-g16-study-runtime-initialization/1.
expected_records is exactly the six canonical native record receipts from /2.
Before each constructor record an exclusive deterministic per-role intent;
after it record {role,file_identity,schema_identity,owner_record_receipts}.
Native store private identity fields are read back from the owner and retained,
never fabricated from Study UUIDs. Completed startup receipt binds all four
per-role receipts. No remote operation occurs before this receipt commits.

Actual owners and required use:

| role | native creator / reader | exact restriction |
|---|---|---|
| Core | native memory Core + export_memory_snapshot, exclusive image publication; §1 existing mutable opener | import six /2 records through Core methods in memory; compare all canonical records and all-table counts before publication |
| Approval | SQLiteApprovalStore(path) absent-only under held directory guard | native O_EXCL reservation, exact native schema; no approvals during initialize |
| Transport | _ProgramTransportStore._create_completion_store(path,approved_root=runtime) | completion-capable v2; NOT v1 create_new; keep its real directory guard |
| Project | _ProductionProvisioningJournal.create_new_recoverable(path,approved_root=runtime) | v3 recoverable creation journal; no Project effect during initialize |

Each role initializer may be invoked only when its file is absent and no
contradictory receipt exists. After interruption, use owner read-only existing
validation first. Adopt an unacknowledged COMPLETE initialized store only if
its exact native schema/identity and expected rows agree with its prior
initialization intent, no unexpected records exist, all sidecars are absent,
and no later effect intent exists. Core unacknowledged image additionally must
equal the exact deterministic native memory export bound by generator identity.
Approval/Transport/Project random native identities are accepted only from their
fully validated one existing store; never regenerate or pick another file.
Missing absent roles can then be initialized once. Partial, empty, wrong-schema,
hot-journal or unknown-prefix files stay retained as initialization-unresolved;
there is no safe native automatic repair API for those cases today. Correct
recovery here means observing/stopping with intact evidence, not guaranteeing
successful continuation after every possible filesystem interruption.

Opening initialized runtime never calls a creating constructor for Core.
Approval uses its existing-file validation branch only after its file identity
is pinned and absence has already been excluded; a narrow existing-only owner
wrapper is required if absence could fall through to its constructor creation
branch. Transport uses open_existing and original v2 guard. Project uses
open_existing / open_existing_readonly as required. Do not turn a readonly
source connection into a write handle or hold Core read_snapshot's transaction
while invoking receipt-source owners requiring an idle connection.

## 5. xTB preparation and exact approvals

Native preparation uses the installed profile, request XYZ and resources;
never arbitrary program data. Map /2 to `model=gfn2,task=optimize,charge=0,
unpaired_electrons=0,solvent=null` and explicit receipt-on-absence-v1 mode in
`_prepare_program_execution_spec`; its native renderer produces `--opt` without
an added tolerance. Executable path/hash, xTB runtime data, PBS renderer and
server root come from the installed resolved profile, never from study CLI.

Actual remote Project chain is `_RTWinProjectAttestor` →
`_ProjectProvisioningService._from_project_attestor` with the durable v3 journal →
`provision_remote_project` / existing exact binding validation →
`_ProgramExecutionSnapshotService._for_production(...).prepare(...)`.
The last call performs current remote Project observation. Therefore run prepare
requires an exact externally reviewed preparation scope binding study/request,
root Project/Attempt, installation/profile, selected remote Project directory,
permitted OBSERVE_PROJECT/PROVISION_PROJECT operations and finite window.
It is not one of the three execution approvals and cannot authorize submission.
This scope is a fixed local review artifact addressed by digest in the installed
registry root, not an arbitrary approval object or a boolean run flag. Its
native acquisition/expiry checker must be specified by the preparation owner;
without it prepare is blocked rather than silently treated as local-only.

Preparation persists exact spec, input, PBS, expanded snapshot and review bytes
exclusively, plus native Project receipt and operation prefix. Interruption may
adopt identical already-written bytes only after native owner validation and
same original IDs; it must not re-provision a Project with an ambiguous outcome.
Project UNKNOWN uses explicit native project reconciliation and no automatic
retry. A retained prepared snapshot must match Core and physical workspace;
never call prepare to recover an already claimed/submitted Attempt.

Review returns these exact bytes/digests and missing authority. An explicit
local `authorize` command records an actual reviewed decision through
ScientificApproval.for_plan, BatchSubmitApproval.for_existing_attempts and
ExactOperationalConfirmation.for_snapshot, then their SQLiteApprovalStore
store methods. The exact one-member batch is xTB's existing PLANNED Attempt.
Do not rely on constructors' default APPROVED: pass the reviewed decision
explicitly. The command takes a digest-bound installed reviewer evidence
reference; no record is created merely because run prepares successfully.
The evidence reference's ownership and full finite fields must be frozen with
the preparation/review adapter, not replaced with a fabricated callback.

After all three records exist and validate, owner publishes
`auto-g16-study-prepared-stage/1` from the session contract and then PREPARED.
Its current field name preparation_receipt_id binds the exact prepared source
receipt; publication after approval is not permission to approve future input.
Its native Publisher basis/qualification/review/evidence bytes must already
be produced by the qualified owner for this exact snapshot. The preparer needs
a bounded native basis-publication function; copying an old task-local basis
and substituting IDs is forbidden. The installed code/Q identity and original
three approvals remain checked by the existing Controller at all checkpoints.

## 6. Submit, collection and restart: the finite vertical slice

`open_prepared_stage(study_id,"xtb")` reconstructs native objects internally,
never changes fixed globals, and calls existing `_run_first_publisher_pilot`
through the reviewed selectors. It preserves `_FixedPilotRun.stores` exactly
Core/Approval/Transport and keeps Project journal separate. The sole durable
claim is execute_once. A used session method stays consumed on exception;
reopening a process cannot bypass original Core submission intent. Any prior
intent takes the recovery path, never submit again. Preserve known SUBMITTED
or terminal facts if a later Study acknowledgement/exit check fails.

Complete xTB vertical acceptance also needs a collection capability, not just
submit. New owner-only `open_collection_stage(study_id, continuation_id)` loads
the existing native exact collection continuation, with an exact registered
`_FixedCollectionRun`/`_FixedCollectionInstallation` pair and current window.
It may invoke `_resume_fixed_publisher_collection` only, not the submit runner.
Extend the four equivalent collection selection/identity sites using captured
session identity; never set _FIXED_COLLECTION_* globals. No public port escapes.
The continuation schema, collector source hashes and checkpoint validation stay
those of the existing native collection owner; do not invent a Study copy.

`_resume_program_collection` already records/consumes the continuation epoch,
refuses consumed incomplete collection, preserves original job binding and can
repair/replay a complete local native bundle. Each collect invocation references
one explicitly approved continuation; new epoch requires new exact review,
never timeout auto-retry. During native scheduler-active state, record the
returned pending diagnostic as distinct from Core UNKNOWN. Existing collection
waits for scheduler absence; scheduler-active program-only completion is a
separate unfrozen feature and not claimed by this xTB slice.

Default recover is local read-only observation of the stable operation/native
prefix. Explicit recover local-repair can only adopt/replay already-complete
native bytes and append a Study acknowledgement. No prepare/stage/qsub and no
remote read can occur in that mode; the existing `_replay_program_completion`
may call checkpoint/driver validation, so its local-only adapter needs mechanical
tripwires and exact proof that no driver invoke occurs. Otherwise use readonly
ProgramReadQuery and report missing acknowledgement until explicit native repair.
UNKNOWN submission reconciliation is separately explicit and cannot resubmit.

Terminal xTB verification uses existing ProgramReadQuery capture/output evidence
and original request/hash. Preserve optimized XYZ, receipt, logs and source
links in owner artifact registrations. Do not claim optimized connectivity or
minimum acceptance from process exit alone. No CREST is automatically started;
its own geometry/seed acceptance remains a later native handoff gate.

## 7. Unified CLI reachability and non-placeholder acceptance

Keep existing local create/review/status/query/audit/default recover semantics.
For /2 only, extend the same product CLI with `run --action` values initialize,
prepare,submit,collect,publish. Directory must match the owner-registered creation
binding; selectors receive only its verified study_id. No module/script callback.
Initialization alone may register the freshly created /2 directory after exact
readback; a separate scripting setup is not required. An explicit `authorize`
subcommand and continuation-registration action must consume the exact reviewed
operator artifacts through the same native adapter. Their closed flags/error
schema are frozen with that adapter before those commands are implemented.

Run submit/collect select already-bound actions; no authority inferred from a
successful previous command. For convenience a local coordinator may return
next required action from persisted receipts, but it cannot automate approvals.
Registry/public result publication is a separate lock entry after owner work,
using the broader public read contract; no CLI subprocess behind HTTP.

An implementation milestone is complete only when synthetic tests exercise
new /2 create → four-store initialize → real native xTB spec/preparation with
synthetic final mechanical peer → native three approvals from explicit fixture
review → prepared registration → actual Controller execute_once → native
collection continuation → result/query/audit → process restart/default recover,
all through this package's declared commands. One initial submission, zero
recovery submissions. No six pre-made snapshots, hand-built callback dictionary,
task-local launch-once script or hidden legacy submit entry can stand in for it.
Target execution is separately exactly approved and runs the same installed
source/entry after qualification. A real xTB pass is xTB vertical only.

## 8. Small remaining contract gaps, not more governance layers

Implementable first: §1 Core opener and its tests. Then independently freeze the
owner-loaded registration/session delta, native four-store initialization and
its adoption tests. The following concrete missing operations are necessary
before the product can run xTB; do not call an always-disabled scaffold closure:

- Preparation operational scope checker and explicit review/three-approval CLI
  adapter, with exact fields and error mapping. Reuse native authority models;
  no new general approval hierarchy.
- Native per-snapshot Publisher basis publication and collection-continuation
  installation/read selectors, bound to the same fixed archive/registry.
- Existing-only Approval open guard (if needed to prevent constructor fallback),
  and local completion repair with an enforced no-wire capability.

These must be specified against their actual native owner code by the main
contract reviewer. They are not authority to guess missing fields. No new
scientific parameters, Q qualifications, callbacks or automatic retry are chosen
here. CREST and two Gaussian Project pairs, geometry selection, thermochemistry,
populations and public browser acceptance remain outside this first vertical
slice. Four-Project identity planning in the broader draft stays intact.
