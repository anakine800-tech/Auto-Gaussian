# Auto-G16 Transport v2 existing-only mutable opener

Status: FROZEN after independent drafting and primary source review on 2026-10-12, for implementation within OD-46 / BUTANE-RELIABILITY-UNIFIED-E2E-01. This contract does not claim implementation or target qualification. Scope is one local native owner entry and its guarded operations. No registry, qualification, remote operation, submission, new receipt schema or scientific authority is introduced. All existing v1/create/open_existing behavior remains on its existing branch.

## 1. Entry and authority

Add a classmethod context manager on `auto_g16.transport.program._ProgramTransportStore`:

```python
open_existing_mutable(
    database, *, approved_root, expected_parent_chain,
    expected_file_identity, expected_store_instance_id,
)
```

It yields the exact `_ProgramTransportStore` type configured for version 2, not a proxy or caller-supplied connection. Implementation may use a new private Transport helper module; no dependency on Study or private Core/Approval/Project owners.

- `database` and `approved_root`: `str` or `os.PathLike[str]` yielding str, canonical absolute lexical paths; bytes, NUL, repeated separator, trailing separator (except `/`), `.`/`..` components, normalization and symlink resolution reject. Database is a strict descendant of the existing approved root.
- `expected_parent_chain`: nonempty tuple of exact two-int tuples for every directory from filesystem `/` through the database parent, in lexical order. Each device >=0, inode >=1; bool rejected. Length must equal the exact component count. It is the already persisted native `completion_guard_binding.component_identities`, converted without adding or dropping components.
- `expected_file_identity`: exact `(device,inode)` tuple with the same numeric constraints.
- `expected_store_instance_id`: canonical lowercase hyphenated UUID string, equal to recomputed native v2 metadata identity. `program_transport_store_id` is derived through the existing metadata algorithm; no second caller authority field.

Caller supplies identities from verified initialization/registration evidence and holds the existing outer Study writer lock. These arguments do not grant approval to arbitrary paths. Native parent lock is the existing completion directory lock, never a new lock file/inode. The caller must not concurrently use another same-process SQLite handle or open/close a descriptor to this database. Entry rejects a matching live `_STORE_HANDLES` handle and any quarantined identity before SQLite; unsupported caller-side legacy opens during the context confer no authority. The installed session must own exactly one Transport handle and never invoke an old opener while this context lives; compatibility of arbitrary mixed legacy/new handles is not promised. This precondition must be enforced by the future session, not inferred from this API. This API does not globally redesign legacy callers.

Failure uses `TransportBoundaryError`, preserving a local cause where useful; interrupts remain their original `BaseException`. Error text is static and contains no payload, command or secrets. Busy remains fail-fast, no sleep/retry. No generated IDs, file reservation, schema creation/migration or repair occurs.

## 2. Pinned lifetime and startup sequence

1. Require native fork/lock primitives and original process. Acquire existing `_directory_guard(database, approved_root)` with its exact process-lock then directory-flock order. Hold its complete no-follow directory chain while validating. Compare its binding to expected_parent_chain before SQLite.
2. Retain an additional lifetime chain and a single target FD opened relative to its held parent with O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC. Require single-link regular file, nonempty valid SQLite header, rollback header bytes 18/19 both 1, matching fstat/stat identities. Freeze startup size/mtime/ctime before any byte read. Reject `-journal`, `-wal`, `-shm` if any exists (including symlink or zero-length). Never unlink/checkpoint/recover them.
3. Open SQLite URI `mode=ro&cache=private`; enable query_only before database inspection. Configure existing native foreign_keys=ON, trusted_schema=OFF, synchronous=FULL without persistent DDL. Validate `PRAGMA database_list` main path, app ID, user_version exactly2, header, schema, native metadata and all rows per §3. Use an explicit read transaction with all cursors exhausted/closed; rollback/end before closing. Recheck startup signatures, identity and sidecars before and after closing ro. No rw connection coexists with ro.
4. Recheck paths/sidecars/signatures under the same native startup directory lock, then open URI `mode=rw&cache=private` (never plain path or mode=rwc), immediately query_only=ON. Repeat actual-path, native schema/metadata/all-row verification. Recheck before the first database-reading statement, and after validation; no initialization or recovery PRAGMA. Missing/replaced/foreign/hot database fails and remains preserved. Do not set journal_mode to repair a WAL file.
5. After all checks, disable query_only on this verified connection and create the guarded handle. Its private lifetime guard retains directory/target FDs until SQLite close is known successful. Release the **startup** completion token and directory lock before yielding. The handle must have `_completion_owner is None` at yield. Full startup contents must be unchanged; business mutation begins only through native write APIs after yield.

Holding directory/target FDs is not holding a completion token or flock. Subsequent operations reacquire the existing `_completion_guard` normally; this avoids deadlocking `_completion_owned` collection. On entry failure, unwind in the same SQLite-before-target-FD order, except uncertain close follows §6.

`_readonly_source_state` opens/closes a database FD; it may supply logic but must not be called while a live guarded SQLite handle could hold locks. All lifetime rechecks use retained fstat and descriptor-relative stat; never reopen/close that inode for attestation. Directory-only walks remain safe with respect to SQLite fcntl locks, but compare against the retained full chain and avoid duplicate lock acquisition.

Root and parent permissions/exclusive Study ownership are the existing cooperative trust preconditions. Neither mode=rw alone nor post-open stat is advertised as protection against arbitrary malicious same-user writes. Deterministic races at each owner boundary must fail before native mutation; retain evidence rather than repair.

## 3. Complete native row validation

Existing `_attest_locked` validates metadata/schema, not all business rows. Add a Transport-owned pure validator, shared by both startup connections, optionally reused at guarded attestation. It must not call `attest_runtime(persist=True)`, record_effect, create or any other writer. Extract existing pure row reconstruction only if needed; retain old byte/identity algorithms exactly.

Validation is within one explicit query-only read snapshot:

- `integrity_check == [('ok',)]`, empty foreign_key_check, exact existing tables/triggers/DDL/application/user version. Reject unknown SQLite inventory and unsupported schema rather than migrate.
- Exactly one metadata row, existing nonce/root/path/device/inode/guard binding/store+instance derivation unchanged; instance equals expected_store_instance_id.
- Every runtime-attestation row: closed payload fields exactly those produced by `_runtime_attestation_record`; native `_runtime_qualification` validation, canonical native encoding, recomputed runtime UUID/digests, all nine stored columns equal reconstructed values; profile/snapshot IDs and protocol/operation table/store/instance match native algorithms.
- Every ordinary physical-effect row: closed payload exactly the current `record_effect` shape; validate base binding and operation request through native validators; classification in SUCCEEDED/FAILED/UNKNOWN, response mapping, job_id validated only as existing native rules require. Reconstruct physical authority UUID, request digest and all 13 columns, including **submit_once_key** only for SUBMIT_QSUB_ONCE. Native canonical encoding must equal original blob. The linked runtime row must exist and match store/instance/snapshot/profile/runtime binding. Unknown additional fields or column/payload divergence reject.
- Every scheduler-raw prefixed row: exact audit-only schema and payload shape; use `_scheduler_raw_payload` plus `_scheduler_raw_values` (or pure extracted equivalent) for byte/hash/type/time reconstruction, linked runtime binding and all columns. Retain UNKNOWN classification and null job/key as stored by current encoder. Do not reinterpret raw diagnostics as effect acceptance.
- Reject orphan rows, malformed canonical blobs, conflicting denormalized fields or malformed submit keys, even if never selected by a later query. Empty business tables are valid. Native rows produced by current writers, including failed/unknown observations, remain valid.

This is **local database consistency**, not proof against malicious coherent database forgery and not full Core/Transport history closure. It does not infer scheduler success, validate scientific outputs or require effects to have already been mirrored into Core; existing receipt-owner complete-prefix validation retains that job. Do not add a new response schema constraint absent from existing writers merely to label this a whole-database validator.

## 4. Normal access, sidecars, threading and locks

Only new handles carry the private lifetime guard. Legacy handles take their original code path. For new handles:

- Bind creator PID and thread; reject foreign thread, fork, closed or poisoned handle before SQL or token use. Existing native `_store_access`, `_completion_guard`, `_require_completion_guard` remain the route to native access and effect owner tokens.
- `_completion_guard` obtains the same native lock per operation/collection. It checks lifetime identity and sidecars after acquiring the lock and before its first SQL; release requires idle connection/no pending cursors and a final lifetime check. The entire long collection may hold the normal native completion token; the *opener context* never holds it for its full lifetime.
- Serialize SQL with the existing store RLock after the directory lock. No new reverse acquisition or registry access. Nested calls already bearing the current native completion token reuse it; do not mint a bypass token or make a second flock call.
- Strictly no WAL/SHM throughout. Outside an owned write transaction, any journal is a failure. Inside this handle's owned native write transaction, a single regular one-link rollback journal under the held parent is allowed; first observation pins its identity and subsequent observations reject replacement. Do not delete/truncate it yourself. Before BEGIN it must be absent; after successful COMMIT or ROLLBACK it must be absent (SQLite default DELETE journal mode). Check journal mode is DELETE, do not change it.
- Database content/size/timestamps may change through successful native transactions, but path/dev/inode/link/ancestor identity and store metadata may not. No frozen initial database digest is imposed on evolved state.
- All detected safety/identity/validation failures permanently poison the handle. Restoring a name or removing a foreign sidecar does not revive it. Cleanup is still permitted as below. Ordinary native conflicting-row rejection rolls back without implying filesystem drift; it must not rewrite history.

Native SQL helpers exhaust/close every cursor, including PRAGMAs and readback; preserve original exceptions if cursor close also fails. Avoid leaving lazy iterators alive when releasing native locks. The guarded branch can use an internal rows/execute helper; unguarded methods preserve existing return/behavior contracts.

## 5. Guarded writes and interruption

All ordinary v2 writes currently converge on `_insert_exact`; new handles must dispatch to a guarded branch, while its legacy branch remains unchanged. No new DDL path is enabled.

Guarded sequence: acquire native store access + RLock; precheck idle/query_only disabled and metadata; reject caller pre-existing transaction **without consuming it**; set ownership of this native BEGIN; protect BEGIN IMMEDIATE, exact insert/replay, row readback, identity/sidecar check, COMMIT, final check within the same BaseException handler. Mark BEGIN ownership before the call so interruption immediately after SQLite executed BEGIN is covered. SQL returned by existing encoders and unique submit_once_key behavior remain byte-identical.

On any BaseException, only if this call owned BEGIN and the same-process connection remains in_transaction, attempt ROLLBACK. Rollback failure preserves the original interrupt/error with a sanitized exception-class note, permanently poisons and quarantines the handle if cleanup cannot be proved. An interrupted COMMIT may already have succeeded: when no transaction remains, do not fabricate rollback or delete committed rows. Report failure/unresolved to caller; native rows are the truth on the next explicit fresh-process recovery. Postcommit identity failure never downgrades Core or re-enters submission.

At context exit, a lingering same-process transaction is never committed implicitly: rollback if safe, report invalid/unresolved and poison. There is no second independent SQLite readback connection in this opener; retained-connection native exact readback plus after-COMMIT guard is sufficient for the existing Transport write contract. Do not reopen the database just for a success check.

## 6. Close uncertainty and fork

Normal close: after final native guard/check, no active token/transaction/cursor, close SQLite exactly once, then release retained target/ancestor FDs each once. Idempotent context cleanup may see an already successfully closed handle; it must not call SQLite close again. An explicit close while native completion token is held rejects (existing behavior).

If SQLite close raises, actual closure is unknown: never mark cleanup successful, never retry the same close and never release the target/ancestor FDs that may affect its locks. Retain connection+guard in Transport-owned process-local quarantine, poison handle, reject reopening the same PID/dev/inode before SQLite. Keep original body exception if present and attach only a sanitized close-error class note; otherwise raise TransportBoundaryError with cause. No reset/retry API. Quarantine is resource retention until process exit/exec, not a disk record or new owner framework.

FD close errors after confirmed SQLite closure are attempted once each with best-effort remaining release, original exception preserved and handle invalid; never retry an FD number that might now designate another resource. Partial construction/fstat failure must obey the same one-attempt ownership rules.

Reuse `_FORK_CHILD_QUARANTINED` and existing at-fork registry. On any child body/context exit: no inherited SQLite method **or property** access (including in_transaction/close/rollback); retain SQLite+target-pin references until child exits/execs; fail. Existing child handling of directory-lock FDs must never issue LOCK_UN on the parent's open file description. Prove parent active write transaction remains intact after child rejection. The new helper must not bypass `_require_store_process` or invent a child reset.

## 7. Independently testable matrix

Use native v2 create fixture offline before entry; all constructor/create/schema-init paths become tripwires during new open. No SSH, PBS or program process required.

1. Valid empty and populated v2 stores: native runtime/effect/raw-audit records, exact duplicate replay, separate Python process reopen; one submit_once key, no new duplicate row. Missing/empty/v1/unversioned/foreign root+instance reject, no file creation or metadata write.
2. All-row corruption: unused bad runtime, orphan effect, wrong indexed column, recomputed payload with wrong submit key, malformed raw record; verify zero startup writes and full source signature preservation.
3. Real hot rollback journal from a killed Python writer, plus WAL/SHM and zero/symlink sidecars: reject without recovering/deleting/modifying bytes. ro→rw replacement and final startup read drift reject; replacement target unchanged.
4. Root/parent/file replacement, symlink/hardlink and name restored after first rejection; permanently poisoned handle. No same-inode reopen/close during live native transaction (instrument FD calls plus independent process SQLite lock contention).
5. Open then acquire/release a real completion guard twice; actual program completion wrapper can acquire it without self-deadlock. Concurrent process guard holder produces fail-fast busy; subsequent explicitly requested operation after release succeeds. Nested/foreign tokens and foreign thread reject.
6. Real append commits; identity change before COMMIT rolls back, after COMMIT preserves row. KeyboardInterrupt injected after BEGIN executed, before COMMIT, after COMMIT; caller catches within outer context and checks no leaked owned transaction. Pre-existing transaction rejection does not consume it. Rollback failure retains interrupt and disables handle.
7. Real fork while parent owns write transaction; child API + actual context exit never touches SQLite, parent retains its lock and commits successfully. New child store open rejects until exec.
8. SQLite close failure before actual close and after actual close; same-process reopen blocked and no pin release/retry; isolate tests in child processes. FD/fstat/cursor-close failures prove no exception masking or repeated FD close attempts.
9. Existing v1/v2 creators/openers, physical effect /1 serialization, completion guard/replay and submission tests remain unchanged and pass. This slice does not activate Study run or confer qualification.

Merge/activation classification remains handbook native filesystem/process safety: local target evidence and independent review are required for the claims exercised here. No new chemistry is needed to test this opener; qualified remote execution and exact scientific approvals remain later gates.

## Read-only source basis

HEAD `8ec3f88e4b9cb6f70213a771f3a35b81cff7cd91`.

- `auto_g16/transport/program.py`: SHA256 `759b9f2b8b0ce68c0cf9db2a60e8fc33510ef6d1255cf72b0126dbef58c8c513`.
- `auto_g16/execution/_project_existing.py`: SHA256 `a1c006f2fa1571cc39b9ba2e08072d8fc5a2578506cdf9d9940616bdf551145e`.
- `docs/v3/contracts/tasks/direct-study-project-existing.md`: SHA256 `a856c17d04d9a583f8d98a969f969953af29c3b2502fc23e495c29d71cd29781`.
