# Auto-G16 local installation publication and initialization CLI

Status: FROZEN local publication and initialization slice after independent draft
and primary review; qualified execution remains excluded.
Continuation of OD-46 and BUTANE-RELIABILITY-UNIFIED-E2E-01. Drafting base:
9452eaf2d524268b59d834570b640a05af93e88c. Read-only development preflight
passed with a clean owned worktree. Implementation and offline validation proceed under the existing exact-scope
Owner authorization; no scientific operation is authorized by this contract.

## 1. Exact boundary

This slice implements a local, no-overwrite installation facts publisher and
connects existing four-store initialization to the installed product CLI.
Publication is a local deployment operation under the user's existing explicit
engineering deployment authorization; this contract does not itself grant that
authority. The publication request records exact inputs, never an approval.
There is no approved flag, installation_id, signature authority, runtime registry,
prepared-stage registration, native session, remote observation or calculation.

[Installation facts](direct-study-installation.md) remains the exact reader,
layout, binding, Git-object, cache and no-qualification contract. Source Git
identity means object self-consistency, not accepted branch/CI provenance.
The installed package and initialization response both remain unqualified for
execution. Existing scientific approvals, Q acceptance and Live Gate still apply.
Neither publication nor initialization constructs a Controller/driver or assigns
_FIXED_* values. A caller may not supply a module, handler or callback.

## 2. Product commands and closed request

Add exactly:

- `python -m auto_g16.study install-local --request PATH --sha256 H`
- `python -m auto_g16.study run --initialize-local --directory PATH`

install-local has no --directory, --force, --resume, root override or optional
publication parameter. --initialize-local is accepted only by run. run without
that flag retains execution-contract-not-frozen before opening any directory.
Existing create/review/status/query/audit/recover behavior and /1-/2 responses
are unchanged. Parser errors retain invalid-request and exit 2.

The installation request is canonical JSON, <=2 MiB, depth <=16, with the same
encoding/duplicate-key/integer/hash rules as the mechanical reader. Its complete
raw bytes must hash to the supplied lowercase SHA256. Fields are exactly:

{schema,destination,source_directory,source_manifest,commit_object,profile,
qualification,roots}

schema = auto-g16-study-local-install-request/1.
source_directory is the existing directory binding from the reader contract.
source_manifest,commit_object,profile,qualification are original file bindings,
with the same reader caps (16 MiB,2 MiB,1 MiB,1 MiB respectively). They supply the
exact bytes to publish, not reserialized or normalized substitutes. roots is
exactly {creation,runtime,registry}, using existing directory bindings. Root
selection is explicit in this one deployment request; later runtime commands
cannot replace it. These facts do not claim root approval or qualification.

destination is exactly {path,parent_chain}. path is a canonical absolute target
directory path under an EXISTING parent. parent_chain is the root-through-parent
ordered array of [device,inode], using the reader's integer rules. The final
target must not exist; there is deliberately no target inode in this request.
No missing ancestor is created. Any existing target, including an empty or
partial directory, file or symlink, returns destination-exists with zero writes.

source_directory, destination, and all three roots must be pairwise disjoint:
none equals, contains or is contained in another. All existing directory chains
are no-follow and physically checked; directory aliases cannot bypass this rule.
The four source artifact files and request file must be outside these directory
subtrees, except that the request file need not have a persisted physical binding
and is held read-only through the operation after its digest check. Artifact
files must have distinct physical identities and satisfy nlink=1. Source files
must not alias artifact files. The new target may share an ancestor with sources
or roots; ancestor identity sharing alone is not a forbidden subtree overlap.

## 3. Validate before publication, then publish through held descriptors

Implement this boundary in private product module auto_g16.study._local_install.
Its sole service entry is publish_local(request_path, request_sha256); no decoded
installation object, builder, port or callable can be injected. It reads and pins
the request, validates its digest/schema and opens all existing source/root/parent
bindings before any mkdir or write. No product subprocess/git/network is used.

Extract the mechanical reader's complete source validation into a shared private
source-tree context if needed: it accepts the bound source directory, exact
manifest and raw commit bytes and retains its own source pins. It checks the
complete inventory, content SHA256, Git modes/blob/tree/commit objects, required
tracked paths, caps, physical uniqueness and cache rules. Both inspect_bundle
and the publisher must use the same validated path. Do not fabricate an
_Inspection via __new__, bypass __init__, make a temporary fake installation,
or substitute a Python-only inventory. This is mechanical reuse, not a new
qualification owner. Cache files are validated under existing rules but never
copied into the destination.

After full source/root/input validation, take a nonblocking exclusive flock on
the retained destination parent directory FD, then recheck parent/source pins
and target absence. Busy returns busy with zero publication. Hold this lock
through final validation and cleanup. This is not a runtime/registry lock; it
must not be acquired while a Study/native execution lock is held.

Reserve destination with descriptor-relative mkdir(mode=0700), open and retain
its FD without following links, verify the named identity, and fsync its parent.
Reserve source/ and installation/ in that retained target in the same way. Each
derived source directory is created once, descriptor-relative, at mode 0700;
all newly created directory FDs are retained through exit. Source traversal and
copy order are deterministic by manifest UTF-8 path order, creating an absent
ancestor only at its first occurrence. No path-based copytree/extract operation.

For every tracked source file, open an absent target with O_EXCL/O_NOFOLLOW and
retain its FD. Read from the already-pinned source FD, copy exact bytes, handle
positive short writes by advancing the offset only, and reject zero write or
write error. File creation mode is 0600; set final mode via that FD to 0600 for
Git 100644 or 0711 for Git 100755. These modes satisfy the reader's exact execute
bits while keeping file contents readable only by the owner; containing
0700 directories prevent access by other users. No pathname chmod. fsync file and parent.
Before each write and at completion verify retained parent chains and target
named identity; any replacement stops, never redirects writes to a substituted
file/directory. Bytes already written to the reserved original inode are retained.

Read every published file back through its held FD. Freeze size/mtime/ctime/
mode/nlink before the FIRST readback, compare at the end, and compare bytes/hash
with the accepted source. Do not accept a post-read baseline. Check source pins
before/after each copy and again before final completion; ordinary source changes
fail closed. No overwrite, truncating reopen, rename-over-existing or deletion.
No retry of failed creation/write/publication and no automatic partial adoption.

Publish installation files in this fixed order:
source-manifest.json, git-commit.bin, profile.json, qualification.json,
study-runtime.json, study-runtime-readback.json. First four preserve original
bytes. Generate locator/readback with the EXISTING closed schemas and bindings
of their final physical paths; commit/tree come only from verified manifest.
Write them exclusively with the same descriptor/readback discipline. Readback
is last and binds locator; no self-hash or cyclic digest. All six filenames and
source inventory must exactly satisfy the reader before success.

Call inspect_bundle on the completed target while all writer/source pins remain
held, consume its exit validation, then recheck original sources, all retained
target identities/content and roots before release. Return success only after
all contexts close successfully. Descriptor cleanup attempts every acquired FD
once, does not retry an ambiguous close, releases the parent lock even on error,
and preserves this operation's original exception with sanitized notes only.
Do not infer the original error from ambient sys.exc_info of the calling frame.
Publication failure preserves the complete/partial target and all bytes; it does
not declare rollback. Even a complete-looking target after an interrupted or
failed return is never overwritten or automatically republished. Existing
inspect_bundle can inspect its facts read-only; another publish to that path
still returns destination-exists.

## 4. Closed publication and initialization responses

Successful publication exits 0 with exactly:

{schema,command,request_sha256,state,installation,qualification_state,
execution_performed}

schema=auto-g16-study-local-install-response/1; command=install-local;
state=local-package-published; qualification_state=not-assessed;
execution_performed=false. installation is exactly
{bundle_binding,readback_binding,source_commit,source_tree,source_manifest_sha256,
locator_sha256}; values are the verified reader facts, copied as JSON data.
It does not claim the publishing process loaded code from that target. Publication
never imports the destination code or sets its process-fixed loader cache.

For run --initialize-local, first enter load_installed_runtime() with no arguments.
Reject unavailable/noninstalled module origin before any store/directory mutation.
Require the creation directory to be a strict descendant of the fixed creation
root, with its entire named chain pinned and no alias escape. It must be a fully
completed native /2 creation; /1 rejects before runtime mutation. No historical
source loaders, catalog or prior Attempt reuse are called. Extract runtime_root
only from loader facts and invoke existing initialize_local(creation_directory,
runtime_root) via a narrow private _initialize_bound owner entry. That entry
compares the complete expected creation and runtime parent chains against its own
held Directory descriptors before the first runtime mutation. Do not reduce a
verified binding to an unchecked reopen-by-path. Retain all installation/root/
creation pins through its return.
The initializer keeps its own bootstrap and per-Study locks in its existing order;
the installation reader takes no Study or registry locks.

Return only after initializer and loader exit checks succeed. Successful response
is exactly {schema,command,action,installation,initialization,qualification_state,
execution_performed}. schema=auto-g16-study-installed-local-response/1;
command=run; action=initialize-local; installation has the same six-field shape
above; initialization is the UNCHANGED existing auto-g16-study-local-initialization/1
response. qualification_state=not-assessed; execution_performed=false. Its nested
installation_state=uninstalled and binding mode=local-uninstalled retain their
historical meaning: no qualified native session is installed. They must not be
rewritten or confused with the separately reported mechanical package facts.
Successful repetition follows existing initialization adoption/replay rules;
it does not create a new identity, store or submission. Installation drift after
local writes reports an error while preserving those writes and their journal.

All failures keep the existing auto-g16-direct-study-error/1 {schema,error}
envelope and exit 2. install-local adds destination-exists and
installation-publication-failed. Reader InstallationFactsError.code passes
through unchanged; existing StudyError codes pass through unchanged. Unknown
publication I/O/copy errors become installation-publication-failed; no raw paths,
exception text or contents appear. Missing request file remains not-found;
request format/hash failures are invalid-request. Missing package inputs before
publication are installation-unavailable. Unexpected initializer errors retain
its existing conservative mapping. No success JSON is printed before exit.

## 5. Required offline verification and excluded follow-ups

Test independent Git-object fixtures plus a complete source fixture with no .git.
Before publication verify hash/schema/caps, wrong commit/tree, mode/content,
symlink/hardlink/alias, subtree overlap, parent replacement and bound-root drift;
all rejected requests cause zero target creation. Test existing empty/partial/full
and symlink targets, duplicate calls and two competing publishers: at most one
exclusive reservation, no overwrites. Test actual short writes, zero writes,
write/fsync/readback failure, same-inode final-read drift, parent/target replacement
and cleanup failures; substituted sentinel files/directories remain unchanged.

Use real child-process interruption points spanning target/directories/source
files/all six metadata publications/final validation. Preserve partial outputs;
republication to the same target always refuses, and the mechanical reader cannot
accept incomplete packages. A complete package's facts may be inspected even
when the publishing process did not return; that is not a publication success
receipt or execution authorization. Record exact expected stdout/exit results.

In a fresh subprocess import the actual installed source and run the real product
CLI, with remote/network/scientific/Controller/registry/session calls tripwired.
Check roots come only from fixed loader, /1 rejection, outside-root rejection,
plain run refusal, exact responses and original management compatibility. Exercise
initialization interrupt/replay through CLI without replacing its existing fault
matrix. Assert one native initial identity set/four stores, zero approvals/effects/
submissions, unchanged immutable creation image, and no implicit qualification.

This slice does not implement mutable-runtime/session reading. inspect_local is
INITIAL-STATE inspection and must not be reused after native stores evolve.
Later readers must bind immutable initialization receipts and physical identities
while native owners validate current mutable states. In particular Project
open_existing currently uses sqlite.connect(path) with create capability and
path-based attestation reopening: it is NOT yet a safely existing-only pinned
session opener. That owner gap needs an exact later contract and validation;
this slice neither changes it nor claims it solved. Registry, actual installation
qualification, accepted source/CI/launch/cache conditions, Q evidence, stage basis,
three approvals, remote preparation, submission and collection remain subsequent
contracts, not permissions inferred from this local CLI success.
