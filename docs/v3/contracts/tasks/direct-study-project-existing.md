# Auto-G16 Project journal existing-only mutable open

Status: FROZEN after independent authorship and primary review for the exact
local existing-only owner boundary below; no native session activation.
Continuation of OD-46 / BUTANE-RELIABILITY-UNIFIED-E2E-01. Read-only preflight
passed on the owned branch at 0d0fd9b82b51b11cccbbe1e8d42940dab068ef65.
Implementation and focused offline validation follow under the existing
Owner authorization; remote operations and submissions remain excluded.
The parent committed that reviewed candidate as 0d0fd9b82b51b11cccbbe1e8d42940dab068ef65
during drafting; this document is the only remaining untracked change.

## 1. Scope and current native behavior

Add one owner-controlled context to _ProductionProvisioningJournal in
execution/project_provisioning.py. It safely opens an EXISTING v3 Project
provisioning journal for its existing local owner operations. It creates no
Project, approval, journal, table, recovery record, remote directory or session
merely by opening. It does not activate a Study runner or qualify installation.

Current open_existing calls _open(create=False), whose mutable branch still
uses sqlite3.connect(path) with implicit creation capability. Current _attest
calls _journal_paths/_journal_file_identity afresh. _record_intent and
_record_success also open independent path-based committed readback connections;
the inherited _append has its own transaction. These paths are not a safe pinned
existing-only context simply because an external wrapper first checks a file.
The new entry must own opening, validation, transaction guards and close.

Keep existing constructors/create_new/create_new_recoverable/open_existing/
open_existing_readonly, legacy _ProvisioningJournal, v2 behavior and their
compatibility tests unchanged. A guarded branch is selected only by this new
entry. It does not silently upgrade a v2 database or alter recovery semantics.
Reuse existing _RECOVERABLE_DDL and native intent/result/binding decoders;
no new persistence tables, schema version, row shape or qualification model.

## 2. Exact entry and physical bindings

Native context manager:

_ProductionProvisioningJournal.open_existing_mutable(
    database, *, approved_root, expected_parent_chain,
    expected_file_identity, expected_journal_identity)

It yields the exact native journal type, with _version=3 and _read_only=False;
no descriptor, raw connection or replacement capability is a supported public
return. database and approved_root accept str or Path whose os.fspath result is
str, never bytes. Require absolute canonical paths with no URI, memory database,
NUL/CR/LF, backslash, empty/dot/dot-dot/repeated/trailing-slash component. Database
must be a strict descendant of approved_root, whose identity is included in the
expected full ancestor chain. Do not normalize invalid input into valid input.

expected_parent_chain is a tuple of (device,inode) tuples from / through the
DATABASE PARENT, exactly matching the number of path ancestors. The approved
root prefix must match the same chain. expected_file_identity is the final
(device,inode) tuple. Device is a non-bool integer >=0; inode >=1.
expected_journal_identity is the canonical native UUID string obtained from the
existing initialization receipt/native metadata identity. Recompute it using
semantic_id('project-provisioning-journal', native metadata), require exact match,
and retain it for the lifetime. This input does not issue or approve an identity.
Reject missing/partial/malformed bindings rather than observing a new baseline.

Caller holds the existing outer Study exclusive lock on runtime/initialization/
for the context lifetime and has authorized access to the fixed local root.
No second advisory-lock namespace, registry or lock stealing is introduced.
The lock coordinates supported owner users; this API does not claim to defeat
arbitrary malicious writers with the same OS permissions. A future session must
supply installed/registered bindings, not unchecked caller-selected roots.

Open / and every ancestor O_DIRECTORY/O_NOFOLLOW, then the existing target
O_RDONLY/O_NOFOLLOW/O_NONBLOCK; no O_CREAT, truncation or mkdir. Retain all unique
FDs until every SQLite connection has closed. Compare every named entry through
its retained parent FD with fstat identity and expected chain; require regular
nlink=1 target and directory ancestors. Missing file may remain FileNotFoundError.
Never fall through to _open(create=...), a creating constructor or initialization.

## 3. Read-only validation before writable connection

Before SQLite opens, reject any -journal/-wal/-shm sibling, including an empty
file or symlink, using retained parent-relative stat. Read the SQLite header
through the held FD, preserving the pre-read size/mtime_ns/ctime_ns baseline.
Reject empty/truncated/non-SQLite, WAL-format bytes, wrong application_id and
anything except user_version=3. File bytes and all sidecars remain untouched.
There is no hot-journal recovery, WAL checkpoint, migration, repair or chmod.
Mode=rw alone must never be described as proving these guarantees.

Open the validation connection using an escaped file URI with
mode=ro&cache=private and isolation_level=None. Set query_only=ON before native
validation. Apply the native connection policy, require rollback DELETE mode
without setting/changing journal_mode, foreign_keys=ON, trusted_schema=OFF,
read_uncommitted=OFF, synchronous=FULL and locking_mode=normal. Require exact
main database path, no unexpected attached database or TEMP schema, native
application/version, exact full _RECOVERABLE_DDL schema, integrity_check=ok and
empty foreign_key_check. A sqlite3 in-memory reference schema may be used solely
for owner schema comparison; no disk DDL is permitted.

Validate EVERY persisted native row, not only metadata or a selected Project:

- provisioning_meta: exactly the native singleton, closed canonical JSON,
  original root/path/device/inode, valid native nonce and derived journal ID.
  Nonce must be the 64 lowercase hex emitted by native creation; do not mint one.
- provisioning_intents: validate all column/payload identities through the
  existing inspect_intent semantics, including canonical serialization and
  semantic_id. An intent without a result is valid persisted ambiguity, not
  permission to retry, finish, observe or recover it.
- provisioning_results: every row has its exact existing intent and canonical
  _load_success payload, matching journal ID, intent ID/hash and parent identity.
  A result without a binding is a valid durable pre-binding prefix. Reject orphan
  results; never insert their missing intent/binding.
- project_physical_bindings: native decode and assert_identity_closed, canonical
  payload, stored binding-ID/project-ID columns exactly equal the decoded values,
  plus exact native intent and creation result correspondence. Associated bindings
  remain excluded from a creation journal by the existing native contract.

Extract an owner-local SQL/state validator if necessary to reuse this check.
Do not call a public opener recursively, execute disk initialization, fabricate
initial state or skip unselected rows. The guarded path may replace only the
physical preamble of _attest; schema/identity checks stay native. Avoid recursive
full-row validation when native row decoders themselves call _attest.

Close the read-only validation connection BEFORE any writable connection is
opened. Recheck full pins, unchanged validation-era file version and sidecar
absence. Then open the original database using mode=rw&cache=private,
isolation_level=None; set query_only=ON before schema/row reads and repeat the
same complete owner validation and physical checks. Verify SQLite's actual main
path matches the pinned canonical target. Only after this succeeds disable
query_only and yield. No BEGIN spans yield. A valid empty v3 native journal is
accepted; a zero-byte, foreign, v2 or partially initialized file is rejected.

The two open phases cannot silently adopt a replacement or changed database.
A replacement before either connection's validation rejects before an owner
write; unchanged expected physical identities remain mandatory on every check.
Preserve original startup byte/version baseline through both read-only checks;
a supported native write after yield may legitimately change content metadata.

## 4. Held guard, native transactions and readback

The guarded handle records creating PID and thread ID, closed and permanently
poisoned state. All supported methods run only on that owning thread; another
thread rejects before SQL. No callback or raw-SQL delegation is accepted.
Any physical/connection/schema/sidecar/fork validation failure poisons it even
if the path or sidecar is later restored. No reset/rebind/revival exists; opening
a fresh context separately requires complete validation again. Methods invoked
after close or from an inherited child fail before SQL. Direct rollback/close
needed for cleanup are allowed even after poison and do not grant continued use.

Physical guard checks use retained fstat/parent-relative stat only; never reopen
then close the same database inode for attestation. Closing an extra FD to that
inode can release POSIX process locks. Directory pins and target FD remain open
until all SQLite connections close. Do not call inspect_initialization or a
read-only opener inside a live native transaction. The only permitted extra
connection is the specifically serialized, post-COMMIT readback below, when
the writer holds no SQLite lock; this is not permission for arbitrary reopens.

Cover ALL three native write paths, not only _record_intent:
_record_intent, _record_success and inherited _append used by append_binding.
The guarded branch uses one owner-local transaction helper, preserving each
method's current insert, conflict, idempotence and readback semantics. Reject a
pre-existing transaction. Check guard immediately before BEGIN IMMEDIATE, after
BEGIN, before COMMIT and after COMMIT. BEGIN, body, COMMIT and postcheck must all
be inside one BaseException cleanup region. An interrupt after BEGIN executes
must still roll back; a COMMIT that succeeded before an interrupt remains durable.
On any failure, rollback only if connection.in_transaction is true. Rollback
failure preserves the original exception, adds only a sanitized exception-class
note, poisons/closes the handle, and never starts a replacement transaction.

No WAL/SHM at any time. During this handle's native write transaction, allow
SQLite's own rollback journal; require no sidecars at idle, after COMMIT/ROLLBACK
and close. Do not delete a residual sidecar to make a check pass. Native methods
must attest immediately before reading and at successful return; owner schema
and complete row checks run at entry/exit and after successful committed changes.
No fixed initial content hash is imposed on a legitimately evolving database.

Preserve independent COMMITTED readback for _record_intent and _record_success;
a query on the retained mutable connection alone is not an equivalent guarantee.
Do not reuse their current unguarded sqlite.connect/close code. Implement an
owner-private serialized readback helper with all these conditions:

- COMMIT has returned; locking_mode is normal and in_transaction is false. Every
  cursor/statement created by the guarded native operation, including INSERT,
  schema checks and prior SELECTs, has been explicitly exhausted and closed.
  The guard tracks native SQL lifecycle; an unclosed cursor is a rejection, not
  an assumption inferred solely from in_transaction. Raw caller SQL is unsupported.
- Set an owner-private readback-active flag before opening a fresh connection;
  all writer SQL/transaction entry rejects while that flag is set. Only the
  creating thread can invoke methods; reentrant writer calls also reject. No
  writer SQL runs until the reader has closed and the flag is cleared. This
  closes the concurrent/reentrant-write window around same-inode reader close.
- Open mode=ro&cache=private, enable query_only, verify that reader's own database
  identity and native policy without a creating opener. Validate retained full
  pins/sidecars before open, after read, and after close. Execute the exact native
  committed-row comparison; fully fetch and explicitly close every reader cursor.
- Close the reader while the writer is still idle under that exclusion. Always
  clear the flag in finally; any reader/close/identity failure poisons the handle
  and preserves the already committed fact. Never retry the reader implicitly.

A small private execution-owner helper module is permitted; it must not import
Study or use Core/Approval private guards. Physical validation does not reopen
files. This exception is exclusively for independent committed readback, never
for a second mutable handle or a reader during BEGIN..COMMIT.

## 5. Exit, errors and compatibility

Normal exit checks no unowned/open transaction, full physical binding, current
native schema/rows and no sidecars; an unexpected open transaction is rolled
back and reported, not silently committed. Exceptional exit rolls back pending
work, preserves the original exception, and attempts the same safe checks.
Successful prior commits remain facts even if later validation/close fails.
No new UNKNOWN state or implicit retry/repair is introduced by this opener.

Close SQLite (and any readback connection) before releasing target/ancestor FDs.
On any cleanup error attempt every remaining resource exactly once, do not retry
an ambiguous os.close on a possibly reused FD, and preserve the actual context
exception via explicit propagation, not ambient sys.exc_info. Without an original
exception, report the cleanup failure. A failure must not claim successful opening/closing. If SQLite close raises,
its result is unknown: retain strong references to that connection, any other
still-live owner SQLite connections, and all guard FDs in a private process-local
quarantine keyed by PID and file identity. Permanently disable the handle and
reject opening that same identity in this PID before any SQLite connection.
Do not retry close or release the pins under a possibly live SQLite lock. There
is no reset, background cleanup or persistent schema/state change; resources
remain explicitly unresolved until process exit or exec permits OS cleanup.
This narrowly supersedes successful cleanup's all-resources-released guarantee;
return the original error with sanitized note or ExecutionValueError, never success. The caller's Study lock is not
owned or released by this API. Forked handles cannot transact. Context exit in the child must not call any
inherited SQLite method/property (including close/rollback): quarantine inherited
connections and pins, and report the fork error. The caller must use controlled
os._exit or exec for that unsupported child; the product does not kill it or
promise that ordinary interpreter teardown of arbitrary forked SQLite use is safe.

Use existing ExecutionValueError and existing native exception mapping; no new
public error envelope is introduced. Sanitize diagnostics; no command, credential,
probe output or arbitrary exception text is added. Missing path remains absent;
all rejected existing bytes/sidecars remain unchanged. Merely opening and closing
a valid store does not append rows. Existing non-guarded paths retain behavior.

## 6. Offline acceptance before later session use

Required tests, using real native v3 SQLite fixtures and subprocesses:

- Open/close with zero row and byte changes; native intent/result/binding writes,
  close, independent-process reopen and exact reads; expected journal ID mismatch.
  Intent-only and intent-plus-result-without-binding prefixes accepted without
  new rows or remote effects;
  existing duplicate intent STOP and binding idempotence/conflict rules preserved.
- Missing/empty/truncated/unversioned/v2/foreign/schema-extra/integrity-corrupt
  inputs; malformed metadata and each row kind, wrong stored columns, orphan
  results, unsupported associated bindings. No DDL/init/migration/creating opener.
- Sidecars including real hot journal made by abruptly exiting a child writer;
  preserve database and sidecar hashes. Header-WAL and zero-length sidecars reject.
- Complete expected-chain validation; symlink/hardlink/ancestor/file replacements
  at ro open, ro-to-rw boundary, before BEGIN, before COMMIT and at exit. Failures
  poison permanently; restoring original names never revives the same handle.
- Real SQLite writer-lock contention proving guard attestations do not release
  the writer's lock; no extra same-inode open/close during a native transaction.
  Independently committed readback still occurs after commit and checks bindings.
  Verify explicit writer-cursor closure, cross-thread and readback-reentrant
  writer rejection, and exclusion through reader close even on reader failure.
- BEGIN-executed interruption, before/after-COMMIT interruption, rollback failure,
  caller catching the exception inside the outer context, and committed-fact
  preservation. Test all three write paths, not one representative method alone.
- Descriptor/SQLite-close failures, fstat failure before FD registration, outer
  already-handled exception isolation, use-after-close/fork, and no stale lock.
  Supported owner cleanup preserves original exception and releases resources.

Tripwire all remote observation, provisioning effects, SSH/PBS/Controller calls;
there is no live test implicit in this acceptance. Keep legacy/v2/read-only/
initialization tests intact. Passing this local owner boundary does not install
a session, make a runtime qualified, or close the scientific E2E chain.
