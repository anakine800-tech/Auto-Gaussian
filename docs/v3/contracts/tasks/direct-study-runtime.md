# Auto-G16 xTB runtime and stage-session composition

Status: section 1 independently reviewed and frozen for local Core implementation
on 2026-10-12; section 1A is independently reviewed and frozen for local Approval implementation;
section 4 is frozen for local initialization after independent author/reviewer
inspection on 2026-10-12; sections 2, 3 and 5 onward remain DRAFT. No live activation authority.
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

## 1A. Approval existing-only mutable open

This narrow Approval owner boundary continues the authorized same-scope work;
independent review confirmed it is required, not an optional wrapper. It does
not freeze §§2–8 or activate a runtime. Add only
`SQLiteApprovalStore.open_existing_mutable(database, *, approved_root, expected_file_identity)`
as a context manager yielding that native store under the caller's existing
Study writer lock. No new approval model, lock protocol or Core/Transport effect.

Never call the creating constructor, reserve, initialization, migration or
repair. Require strict absolute canonical paths, containment, every ancestor
opened no-follow, regular target with nlink=1 and exact non-bool device/inode
pair, matching §1. Hold the complete descriptor chain until all SQLite
connections close. Reject inherited/forked or permanently poisoned handles.
Before SQLite opens, use the held target descriptor to check the SQLite header,
rollback journal format, Approval application_id and user_version. Reject all
journal/WAL/SHM sidecars including empty files. Recheck retained descriptors and
names, without reopening/closing the live SQLite inode for attestation.

First open mode=ro&cache=private, query_only=ON, and apply Approval's connection
policy and `_validate_open_database`: exact schema, integrity_check and complete
row decoding/canonical evidence identity remain mandatory. Close the validation
connection and recheck identities/sidecar absence before opening mode=rw with
query_only=ON. Repeat the same owner validation, then disable query_only and
yield. Empty but valid initialized Approval databases are accepted; missing or
zero-byte databases are not. Mode=rw alone is not a no-recovery guarantee.

The optional guard is checked on `_db`, at BEGIN, before COMMIT and after COMMIT.
No sidecars at idle/close; SQLite's own rollback journal within an active native
transaction is permitted. Any identity/sidecar/fork check failure permanently
poisons that handle even if names are restored. On interruption/exception,
rollback any uncommitted transaction, preserve the original exception, report
exit validation failures as sanitized exception notes, close SQLite and then
release descriptors. A successful committed approval remains a fact if later
exit validation fails. Existing constructor/read/write semantics are unchanged
outside this guarded entry. Public callers use only existing owner methods,
not the raw SQL connection. The three evidence domains, current snapshot checks,
idempotence and conflict rejection remain exactly the native contract.

Use existing Approval errors; missing file may remain FileNotFoundError.
Rejected files and sidecars stay unchanged. No approval or default APPROVED is
created by opening. Test all three evidence domains across a real process
restart and repeated writes, missing/empty/foreign/header/schema/record failures,
real hot journal retention, aliases/hardlinks/ancestor or target replacement,
permanent poisoning after restoration, precommit rollback, committed-fact
retention after interruption, startup query-only ordering and held-FD lifetime.
Tripwire the creating constructor, reservation and initialization; retain all
existing Approval tests. This local API success is not installation, native
execution qualification, xTB vertical completion or scientific acceptance.

## 2. Fixed installation and owner-loaded session entry

The local mechanical package reader is now frozen separately in
[installation facts](direct-study-installation.md). That exact contract supersedes
the proposed installation-object fields below for its own zero-effect slice.
It grants no qualification and does not activate this section's stage session.
The remaining installation/registry/preparation/session contracts stay DRAFT.

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
and physical root chain along with the source-manifest hash. No general qualified native installation owner currently exists. The new
mechanical readback validates facts only and avoids a self-referential manifest
hash; the explicitly reviewed deployment operator and later native Controller
checks continue to own qualification and approval semantics. The archive manifest binds actual loaded source
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
while selecting the exact immutable entry, release registry, Study exclusive on runtime/initialization/,
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

## 4. Independently implementable local initialization slice

Status: frozen for the local-only implementation described here, independently
reviewed against native owners on 2026-10-12 after drafting at
1f747026a64af4e6ee9cb0d3f3a3500d9e4df775. Implementation starts from
be7c353a9a9310d4d90f8a4826b81c4567fcd92b with read-only preflight PASS.
This same-scope Owner continuation retains commit/publication/review authority,
requires the stated fault matrix, and leaves every installation/live gate intact.
Only local initialization and explicit adoption are frozen here.

### 4.1 Entry, identities and excluded effects

Private product module `auto_g16.study._runtime_initialization` exposes exactly
`initialize_local(creation_directory, runtime_root)` and
`inspect_local(creation_directory, runtime_root)`. Both arguments are canonical
absolute local path strings, not callbacks, decoded capabilities or CLI flags.
The caller has already selected an authorized local root; these functions do
not grant authority over an arbitrary root. No historical source is accepted.
Both verify the complete immutable /2 three-event/four-file creation directory
with its existing parser, canonical request, six native records and exit pins.
Incomplete /2, /1 reuse, foreign schema or changed creation bytes reject.

study_id is the existing /2 project_id; creation_key and all eight reserved
slots are unchanged. Runtime destination is exactly runtime_root/study_id.
Only the six initial xTB records are materialized. No CREST/Gaussian Project,
Task, Attempt, approval, effect, snapshot or result is produced here.

This private API is locally callable and fully testable without an installed
execution binding. It is not exposed by the production CLI, HTTP, registry or
session factory in this slice. Existing run rejection remains before any open.
Local initialization records explicitly say `mode=local-uninstalled` and
contain NO installation_id/profile/qualification/approval claim. Later qualified
installation must validate and bind this exact completed receipt by a separate
append-only publication; it cannot rewrite these files to pretend initialization
was qualified. §§2/3/5 onward remain blocked where their contracts are open.

### 4.2 Physical layout, locks and bootstrap failure

runtime_root must already exist, be distinct from and neither contain nor be
contained in creation_directory, with a held no-follow full ancestor chain.
Destination and all children are new directories mode 0700/files mode 0600,
subject to restrictive umask; no permission broadening of existing objects.
Physical directory binding is exactly {path,parent_chain,file_identity}, where
path is canonical absolute, parent_chain is the ordered [device,inode] array
from filesystem root THROUGH the target directory, and file_identity equals
its last pair. Device is a non-bool integer >=0 and inode >=1. Symlinks,
non-directory ancestors, aliasing identities or substitution reject.

Lock order for these two entries is creation directory shared, runtime_root
exclusive for initialize/shared for inspect, then runtime/initialization/
exclusive for initialize/shared for inspect. All are nonblocking flock on held
no-follow directory descriptors. After acquiring the initialization lock and
checking its binding, release runtime_root's lock but retain its descriptors;
never reacquire that lock inside this call. If destination is absent,
initialize reserves it with descriptor-relative mkdir, then initialization/,
then acquires that child's lock. inspect never creates a directory or file.
An existing destination without a valid first initialization event is unresolved,
even if empty; no automatic adoption of a crash before the first durable intent.

All future Study runtime coordination must use this SAME initialization-directory
lock inode. The runtime root itself is pinned but not flock-locked by Study
while invoking Transport. Transport's native completion guard continues to lock
the database parent runtime/, with its original process guard; these are distinct
inodes. No native guard is skipped or borrowed. Source/registry publication lock
ordering remains a separate entry as in §3, not nested here.

The closed runtime child inventory after completion is exactly:
`initialization/`, `operations/`, `prepared/`, `artifacts/`, `reviews/`, `public/`,
`binding.json`, `core.sqlite3`, `approval.sqlite3`, `transport.sqlite3`,
`project-journal.sqlite3`. At an incomplete prefix only named subsets permitted
below exist. The five directories other than initialization/ are empty throughout
this slice. Initialize creates them, in the listed order, after event 0001;
existing empty real directories are adoptable only under that intent. Any content,
unknown filename, later operation, symlink, hardlink or sidecar is unresolved.
Directory mutations and files are fsynced with their containing directory.
There is no temporary-file rename, overwrite, deletion or repair path.

### 4.3 Closed journal and receipts

Use the existing Study canonical JSON encoding: UTF-8, sorted keys, compact
separators, no NaN, no duplicate keys; raw bytes must equal canonical encoding.
Each file <=2 MiB, nesting <=24, no unknown fields or bool-as-integer. Digests
are lowercase SHA256 hex; UUIDs canonical; no timestamp-derived identity.
All creation and runtime bindings remain pinned and checked through exit.

Exactly ten immutable events live in initialization/, named:
`0001-intent.json`, `0002-core-intent.json`, `0003-core-receipt.json`,
`0004-approval-intent.json`, `0005-approval-receipt.json`,
`0006-transport-intent.json`, `0007-transport-receipt.json`,
`0008-project-intent.json`, `0009-project-receipt.json`, `0010-complete.json`.
Each envelope is exactly {schema,sequence,previous_sha256,event_id,kind,data},
schema=`auto-g16-study-local-initialization-event/1`, sequence=1..10,
previous_sha256=null for 1 and otherwise the immediately preceding raw digest.
event_id=UUID5(creation_key, `auto-g16-study-local-initialization/1:event:N`),
where N is the decimal sequence without padding. Kinds are INITIALIZATION_INTENT,
then alternating STORE_INTENT/STORE_RECEIPT four times, then LOCAL_COMPLETE.
Only contiguous prefixes are accepted; partial/malformed files remain evidence
and block further writing. Exactly one publication attempt per missing filename;
O_EXCL conflict causes revalidation/reporting, never overwrite or in-call retry.

Event 1 data exactly {mode,study_id,request_sha256,creation_binding,
creation_event_sha256,creation_core_sha256,runtime_binding,lock_binding,
core_image_generator,expected_records,store_order}. mode=local-uninstalled;
creation_event_sha256 is an ordered three-element array of /2 event digests;
core_image_generator is the existing _fresh_model.generator() closed schema;
expected_records is exactly the six existing /2 record receipts in native order;
store_order is [core,approval,transport,project]. Binding fields follow §4.2.
No installation claim or synthetic native store identity is inserted.

Each STORE_INTENT data exactly {role,filename,initialization_intent_sha256,
expected_schema_version,expected_state}. Role/filename map is core/core.sqlite3,
approval/approval.sqlite3, transport/transport.sqlite3, project/project-journal.sqlite3.
Versions are the current native Core SCHEMA_VERSION, Approval 1, Transport 2,
Project 3. expected_state is exactly {records:expected_records} for Core and
{empty:true} for other roles. The intent is durably committed before invoking
any native creator or publishing the Core image. No earlier role is reopened
for mutation; fixed order is mandatory.

Each STORE_RECEIPT data exactly {role,intent_sha256,file_binding,state}.
file_binding is {path,parent_chain,file_identity}, with parent_chain through
runtime/ and file_identity the target regular one-link file. state is the
owner-produced closed state below. No whole-file hash is used as a permanent
identity for a mutable runtime store. Event 10 data exactly
{study_id,request_sha256,binding_sha256,store_receipt_sha256}; the last field is
an ordered four-element array of STORE_RECEIPT raw digests. The final event_id
is the local initialization_receipt_id referenced by later integration.

After all four receipts, publish binding.json once, then event 10. Its exact
schema is `auto-g16-study-local-runtime-binding/1`, with fields
{schema,mode,study_id,request_sha256,creation_binding,runtime_binding,lock_binding,
initialization_intent_sha256,store_receipt_sha256}. Values must equal the proven
prefix. An existing exact binding.json after event 9 can be adopted; any differing
or partial bytes block. This local binding is never overwritten by the proposed
installed binding from the broader execution draft.

### 4.4 Native creators and owner-only initial-state inspection

Core uses _fresh_model.records and public Core persistence methods in memory,
then export_memory_snapshot and descriptor-relative exclusive image publication.
No disk constructor initializes the Core destination. The initial image must
match all six canonical records and a complete all-table inventory: the six
record tables have exactly one row each, all other native tables have zero rows.
For unacknowledged Core bytes additionally require the saved generator to equal
the current generator and exact bytes equal a fresh native memory export.
A previously acknowledged image is validated semantically, not regenerated.
The immutable /2 creation image retains its own historical generator/hash: it
need not match the current runtime generator after a source update and must
never be reconstructed or replaced. Event 1 binds the current runtime image
generator separately. An unacknowledged runtime Core image with a changed
generator is unresolved even if its selected six records happen to match.

Approval, Transport and Project each add the narrow native entry
`create_initialization_at(database, *, approved_root, parent_chain)`. It accepts
only its fixed runtime basename, immediately under approved_root. parent_chain
is the exact full root-through-parent ordered [device,inode] sequence already
held by Study, with non-bool integers. A private mechanical helper in
`auto_g16/_initialization_file.py` may implement retained descriptor reservation
and byte publication; schema generation/validation remains in each native owner.
This is not a general database export or caller-supplied builder API.

Before reserving anything, the owner walks/holds the full no-follow chain and
compares it with parent_chain. Transport additionally acquires its original
native directory guard and verifies its component identities. Reserve exactly
once through the held parent FD using O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600.
Hold the target FD through exit. No disk SQLite connect, path reopen for writing,
truncate, rename, overwrite or fallback is permitted. Build the original native
schema in SQLite memory, retaining native application/version, exact DDL and
triggers. Approval has zero evidence; Transport v2 uses its actual 32-byte nonce,
native store/instance algorithms and original guard binding; Project v3 has its
actual random nonce/meta. Paths/root and dev/inode in metadata bind this reserved
file. Do not fake disk connection policy to reuse disk-only attestations.

Commit and validate the memory image's exact schema, full initial rows,
integrity and foreign keys before serialize. Publish at most 16 MiB solely
through the retained target FD with short-write handling, fsync it and its
original parent, verify length/hash, and recheck the entire named/held chain.
Any drift or interruption fails; never write a replacement object or delete
original residual bytes. Only {file_identity,size_bytes,sha256} may be returned,
not a store handle, approval or initialization-completion claim. Study then uses
the separate native inspector. A missing receipt never allows truncating or
rewriting an existing reserved file. This necessary descriptor-bound correction
was independently reviewed on 2026-10-12; it supersedes the earlier path-only
creator plan without enabling production execution.

Required additional negatives: parent replacement after entering creator,
target replacement after reservation, serialization/short-write/interruption/
fsync/exit failures, repeated creation and zero writes to replacement objects.
Existing native readers must accept each complete image unchanged. Existing
production creators and their validators keep their behavior.

Add narrowly owned classmethod `inspect_initialization(database, *,
approved_root, expected_file_identity)` to each of the four store classes.
Core additionally requires keyword `expected_records`, the exact six typed
Core records from the validated /2 request. These are read-only inspectors,
not general query APIs or writers; all reject non-initial contents. They return
a detached state only after native checks, exit checks and handle closure.
Study never reads private SQL tables or invents native identity fields.

Each inspector requires the full no-follow path/one-link/sidecar/header checks
from §§1/1A and the original owner schema and row validation. It cannot call a
creating constructor, change journal mode, checkpoint, recover a hot journal,
initialize or migrate. Only mode=ro/query_only is used; no writable connection.
Core reuses read_snapshot and its schema checks inside retained outer pins;
Approval reuses its held guard and ro portion of §1A plus complete row decode;
Transport uses _open_readonly_existing and its native v2 guard; Project uses
open_existing_readonly and its v3 attestation. Do not call Project.open_existing:
its current non-readonly sqlite3.connect(path) still permits file creation.
The inspector must validate expected file identity before and after native
open, schema integrity, all-table counts, and names/sidecars through exit.
Preserve each existing read-only owner attestation policy; no mutable handle is
open during inspection, and never introduce a target reopen/close alongside a
mutable SQLite handle or its transaction locks.

Returned common fields exactly {schema,role,file_identity,schema_version,
schema_sha256,owner_state}, schema=`auto-g16-native-initial-store-state/1`.
schema_sha256 is SHA256 of canonical sorted {name:sql} for all native non-SQLite
schema objects, compared against the owner's exact declared inventory, not a
caller-provided inventory. owner_state is closed by role:

- Core: {records,table_counts}; records are the six canonical record receipts;
  table_counts has exactly every current native table name and its integer count,
  constrained as above. This counting/receipt comparison remains in Core.
- Approval: {evidence_count}; value 0 after validating every evidence row.
- Transport: {program_transport_store_id,store_instance_id,table_counts}; IDs
  are the native attested values. Counts exactly program_transport_meta=1,
  program_runtime_attestation=0, program_effect_physical_authority=0.
- Project: {journal_id,table_counts}; journal_id is the native semantic identity
  of its validated meta. Counts exactly provisioning_meta=1,
  project_physical_bindings=0, provisioning_intents=0, provisioning_results=0.

No raw creation nonce, connection, guard, callback or capability is returned.
Post-creation inspection failure retains all files and reports unresolved; it
never authorizes rerunning that creator. Existing mutable openers are NOT needed
for initialization adoption and are not called by either entry in this slice.

### 4.5 Restart/adoption, output and validation

inspect_local is strictly zero-write, including no acknowledgement/publication.
If runtime destination is absent return not-found. For an existing valid prefix
return its verified state and next_local_step; invalid prefixes are unresolved.
initialize_local is the only explicit resumptive writer: it may publish a missing
receipt for a COMPLETE store under its own prior intent after reinspection, then
continue the fixed suffix. It may create an absent role only after its durable
intent. Store present without its role intent, receipt without file, later file
without its earlier prefix, partial/empty database, unknown native version,
nonempty initial business table, sidecar or physical drift blocks, retaining bytes.
On complete reentry revalidate all four initial states, binding and creation;
return the same receipt with zero writes. Once any native runtime operation has
started, these initialization entries cannot reset, repair or reclassify that
runtime; a future operational reader uses a different exact contract.

The returned object is exactly {schema,study_id,request_sha256,state,
initialization_receipt_id,journal,next_local_step,execution_performed,
installation_state}; schema=`auto-g16-study-local-initialization/1`.
state is initializing or local-initialized; receipt_id null until event 10.
journal is the ordered committed prefix [{sequence,kind,event_id,sha256}].
execution_performed=false and installation_state=uninstalled. next_local_step
is null when complete, otherwise one of create-directories, core-intent,
core-store, core-receipt, approval-intent, approval-store, approval-receipt,
transport-intent, transport-store, transport-receipt, project-intent,
project-store, project-receipt, binding, complete. For an intent with an existing
valid complete store, next step is its receipt; absent store means store.
Existing StudyError codes only: invalid-request, not-found, busy,
initialization-unresolved, invalid-evidence. File presence/schema/unsafe path or
unknown prefix in a destination maps unresolved; foreign /2 input maps
invalid-evidence. Lock contention maps busy; no retry. No exception text leaks.

Required offline evidence: complete creation through all four native creators;
real child exit before/after each intent, constructor/image publication and
receipt, binding and completion; new-process inspection and explicit adoption
with same IDs/native nonces, no double constructor, immutable prefix preserved;
actual two-process Study lock competition and native Transport guard coexistence;
all-table nonempty/malformed/sidecar/partial/header/schema/identity negatives;
complete repeat zero-write; post-effect nonempty runtime refuses initialization;
no default-recover writes; source and destination exit drift; closed descriptors
and exceptions; all installed/remote/science/approval effect APIs tripwired.
These tests do not qualify a runtime installation or claim xTB/whole-chain E2E.

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
- Required §1A existing-only Approval owner entry, and local completion repair
  with an enforced no-wire capability.

These must be specified against their actual native owner code by the main
contract reviewer. They are not authority to guess missing fields. No new
scientific parameters, Q qualifications, callbacks or automatic retry are chosen
here. CREST and two Gaussian Project pairs, geometry selection, thermochemistry,
populations and public browser acceptance remain outside this first vertical
slice. Four-Project identity planning in the broader draft stays intact.
