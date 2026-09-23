# Auto-G16 v3 boundary: v31-controller-guard

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [V31-PBS-COMPAT-FILE-COMPLETION-01 candidate boundary](v31-file-completion.md#v31-pbs-compat-file-completion-01-candidate-boundary)
- [C3 rendering-material supplement candidate](v31-file-completion.md#c3-rendering-material-supplement-candidate)
- [V31 publisher R4 private offline boundary](v31-successors.md#v31-publisher-r4-private-offline-boundary)

<!-- Moved from docs/v3/boundary-spec.md:5664-5848 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### C4 native controller directory guard proposal

**PROPOSED / OWNER ACCEPTANCE PENDING.** C4 is a replacement candidate for
C2's database-inode completion lock, not active implementation authority.
C2/C3 acceptance and the retained offline implementation remain historical
facts. C4 becomes effective only on exact Owner acceptance of the reviewed
six-file manifest and candidate commit. The task's production publisher hard
stop remains unconditional; native probe success cannot qualify a publisher.

#### Exact delta and private identity

Only receipt-mode completion on fresh stores is proposed to use a retained
no-follow descriptor of the **existing parent directory** of its bound
ProgramTransportStore, with nonblocking exclusive POSIX flock. This is a
conservative directory-wide lock: different stores in one parent also contend.
Never flock the SQLite database. Default SQLite VFS, journaling, transactions,
foreign keys, trusted_schema=OFF and synchronous=FULL remain unchanged; no URI
VFS substitution, locking_mode workaround, sidecar lock file or new directory.

A fresh private store version is necessary: an in-memory parent observation
cannot reject a database moved into a replacement parent after restart. Add
only private schema `auto-g16-v31-program-transport-store/2`, application_id
1093879637 (unchanged), user_version 2, with the existing meta DDL extended by
`,completion_guard_binding BLOB NOT NULL` immediately before its final `)`.
All existing meta columns, other table definitions and append-only triggers
retain their names, order and constraints. Version-2 schema_identity is existing
Transport canonical_bytes over the ordered version-2 DDL statements followed
by the ordered unchanged trigger statements; exact inventory is reattested.
This is not a Core migration or a third public execution record.

The new BLOB is canonical_bytes of exactly this closed mapping:

- `schema`: `v31-completion-directory-guard/1`;
- `lock_directory`: the exact absolute lexical dirname of approved_store_path;
- `component_identities`: an ordered list of two-integer lists `[device,inode]`,
  one for `/` then each directory component through lock_directory, inclusive.

Each device is an exact nonnegative integer and each inode an exact positive
integer; booleans, unknown keys, duplicate keys, noncanonical encodings and
wrong chain length reject. Absolute root/path must have no dot/dot-dot, empty
interior component or trailing separator (except `/`), must already equal
abspath, and must retain the existing strict approved-root containment. Do not
resolve a symlink into an accepted alternate spelling. Walk every component
from `/` with descriptor-relative O_DIRECTORY|O_NOFOLLOW; retain and compare
its device/inode, type and named identity. The approved root occurs at its
exact position in this chain. Store file is a no-follow regular file with
st_nlink exactly 1, the bound device/inode and exact approved lexical path.
Directory link counts need not be 1. No mode or timestamp is an identity field.

Version-2 logical store ID uses the unchanged program-transport-store domain
and existing schema/root/path payload with schema `/2`. Instance ID uses the
unchanged program-transport-store-instance domain and existing version-2
payload (including nonce hash and database device/inode), adding exactly
`completion_guard_binding_sha256` = Transport `_digest` of the mapping above.
Store records keep their existing shapes and close these exact version-2 IDs.
Every private record payload using the store schema discriminator dispatches
on that attested store version, including runtime attestation and physical
effect authority; never replace a global `/1` constant to route old records.
Unknown or mixed store/payload versions reject. Read the persisted binding and
compare it exactly; never derive a replacement binding from the current path
and write it back.
No ID occurs inside its own preimage; the binding includes no instance ID or
container hash. Attempt/job/snapshot/physical-workspace closure remains the
existing authority chain through those store IDs, not a new workspace record.

#### Creation, opening and compatibility

Propose one private factory `_ProgramTransportStore._create_completion_store`
with the existing path/approved_root arguments. It creates version 2 only at
an explicitly approved fresh local database path in an already existing real
parent. It acquires the directory guard, reattests the full chain, reserves the
database descriptor-relatively with O_CREAT|O_EXCL|O_NOFOLLOW, then initializes
and re-reads the exact version-2 schema/binding under the same guard. Creation
failure retains the partial file; it grants no automatic repair, deletion,
replacement, reuse or retry. SQLite's existing transaction/journal behavior is
not a new cleanup authority. No separate lock artifact is created or removed.

Existing create_new remains version 1 with exact historical behavior. Existing
open_existing gains closed version dispatch; version 1 attestation, strict
serialized IDs, strict queries and strict proof behavior remain unchanged.
Version 2 is explicitly provisioned for new receipt-mode Attempts only; there
is no caller boolean, environment override, implicit upgrade, migration command
or copying of earlier authority into a new store. Opening version 2 takes the
guard and reattests its persisted chain before allowing store operations.
Every reopened handle has a new live owner context, not inherited authority.

Receipt-mode entry under C4 requires version 2 before effects or epoch writes.
Version-1 receipt histories remain readable as historical raw evidence, but
C4 collection, reduction, replay completion and promotion reject them with a
boundary error `completion-store-not-qualified`. Do not reinterpret, migrate,
reapprove or finish those Attempts automatically. This narrowly supersedes the
C2 database-inode guard and its receipt-mode old-store eligibility; it does not
change any C3 rendering material, ProgramSpec, snapshot, receipt, assessment,
byte-bundle, proof or public Transport operation schema. Existing strict mode
uses version-1 stores; passing a version-2 store to strict composition rejects
before effects instead of silently changing strict store identity.

Default sqlite3 opens by pathname. Retain/recheck parent descriptors and the
named database identity before and after SQLite open, before its first schema
read/initialization, and at each later guard boundary. Do not claim a native
SQLite descriptor-relative open or close arbitrary extra database descriptors
while SQLite POSIX locks are live. The qualified local namespace must stay stable for the entire SQLite
connection lifetime, including journal/auxiliary paths: no participant or
external maintenance process may rename, relink, mount over or replace it.
An uncoordinated topology writer is an unqualified composition, even if its
intent is benign. Detected drift invalidates the handle and stops further
work; SQLite may already have performed local recovery/initialization before
a post-open failure. Therefore zero driver calls/epoch writes is not a claim
of zero local SQLite effects on a drifted namespace. No resume, deletion or
repair is inferred. This stable-namespace precondition is essential to using
the default VFS; arbitrary concurrent replacement is not a supported topology.
The existing OD-18 local trusted-controller model applies: no claim of defeating a malicious same-UID rename actor,
root/kernel/filesystem compromise, or trusted deployment compromise. Qualified
participants never rename/replace bound stores or parents. Observed no-follow,
alias or identity failures stop; ordinary pathname checks cannot be advertised
as an atomic defense against excluded actors. Remote descriptor-relative
mutation requirements are unchanged and are not weakened by this local clause.

#### Ownership, lifecycle and effect ordering

Before trying flock, take a nonblocking process-wide registry lock keyed by
`(pid, directory_device, directory_inode)`, shared by every handle and thread.
Keep registry entries alive for the process lifetime so removing an entry
cannot split ownership. No waiting loop or retry. Retain the no-follow directory
FD for the whole operation; only its acquiring owner can release it. Reattest
full persisted directory chain and database identity after acquisition before
body entry. Busy, unsupported locking, missing binding or pre-body drift yields
a boundary error with zero driver calls and zero epoch writes.

A private unforgeable held token binds exact store object, store instance ID,
process ID, thread ID, directory identity and live descriptor ownership.
Internal nested calls must receive this exact token; they cannot relock a
shared FD to manufacture ownership. Foreign, missing, stale, cross-thread,
cross-process and closed-store tokens reject. Non-owner close while a guard is
held rejects; close must never silently release another thread's ownership.
An owner cannot close its store inside the guarded body. Closing a different
handle does not release the guard. All version-2 store writers participate;
internal writes use the already held token, external writes acquire one guard.
There is no second nested physical acquisition or public token API.

Register a private at-fork discipline before any guarded FD can exist. A small
registry mutex covers FD creation/registration and unregister/close; before
fork takes this mutex, the parent callback releases it, and the child callback
closes each inherited guard FD **without LOCK_UN**, invalidates all inherited
tokens and store connections, resets the process registry and releases its
local mutex. Closing the child's duplicate must not unlock the parent's open
file description. Child operations, including close, reject inherited stores by creator PID
before any RLock or SQLite access. Retain inherited SQLite objects in a private
child quarantine without close or destructor-driven disposal. A qualified
fork child only proceeds to exec or os._exit after the minimal at-fork handling;
it cannot run a fresh SQLite connection in the inherited interpreter or use
normal Python teardown as connection cleanup. A new independent process may
explicitly construct a fresh store after exec; no automatic reopen occurs.
CLOEXEC/non-inheritable FDs prevent exec inheritance. Registration failure or
unsupported primitives reject C4 use; no weaker fallback is allowed. Registry
critical sections call no user code and never fork. Native tests must verify
this discipline rather than infer it from CLOEXEC.

Release flock, close descriptors and release the in-process lock in nested
finally paths; retained history remains intact after exceptions. OS descriptor
release after process death permits a later explicit acquisition, not automatic
recollection or restart. Failed release/close invalidates that owner/handle;
never continue a completion claim with uncertain ownership.

Keep this same guard across full dual-store history reload, scheduler epoch,
receipt/output acquisition, public Result append and re-read, assessment
append, prefix recheck, Core transition and proof/replay validation. Reattest
current named full chain, database nlink/device/inode and persisted binding
before each effect or evidence write and immediately before reduction/promotion.
If drift occurs mid-body, stop further effects/writes/promotion, retain any
already acquired/appended evidence and do not rollback or retry. Reopening a
moved same-inode database cannot acquire authority from its new parent: the
persisted chain mismatches even though the replacement directory's raw flock
can succeed. Hard links, copied databases, symlink components and alternate
lexical aliases reject; aliases which share the parent inode still contend on
one physical lock. A rename/replacement of any ancestor invalidates the chain.

This serializes existing public Core calls; it is not an atomic cross-store
SQLite transaction. Direct Core/Transport writers bypassing the existing
Execution owner remain an unqualified composition. It introduces no new Core
lock, private SQL access, legacy v2 receipt/capability framework, live operation
or scientific authority. Linux-only or mocked tests cannot close native Mac
acceptance; absent platform/filesystem evidence remains NOT QUALIFIED.
