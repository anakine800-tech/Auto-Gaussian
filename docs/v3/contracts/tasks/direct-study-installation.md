# Auto-G16 local installation facts and fixed locator

Status: frozen for the local-only mechanical implementation after independent
author/reviewer inspection on 2026-10-12. No production activation authority.
Continuation of BUTANE-RELIABILITY-UNIFIED-E2E-01, OD-46 and the Owner-authorized
four-part work. Drafting base ca11f1112331bb63f3b191070e24656657c6b30b;
read-only development preflight passed with a clean owned worktree on 2026-10-12.
The independent drafting task edited only this document. The implementation
continues the same Owner-authorized scope; tests are offline and no installation
or live operation follows from this freeze.

## 1. Exact slice and authority

Implement local installation-package FACT validation and a no-argument fixed
locator reader. Neither creates an installation, approves a root/profile/Q,
issues a qualification, registers a Study, constructs a session/driver, nor
changes any _FIXED_* value. Existing public Study run refusal remains unchanged.
Do not call this a replacement native qualification owner: no such general
installation owner exists in the current code.

The existing R4 installation trust boundary remains the explicitly authorized
deployment operator's installation and interpretation of exact original evidence.
The new reader checks installed facts, not who approved them. A self-consistent
package yields only mechanically-verified, with execution_enabled=false and
qualification_state=not-assessed. No dictionary field can switch either value.
The existing Controller's exact three approvals, Q/profile/source checks,
reviewed semantics, accurate snapshot basis and finite Live Gate remain later
mandatory checks. A hash match is not a deployment or scientific decision.

This minimal slice verifies the complete source Git object identity rather than
only trusting commit/tree labels. It uses standard-library SHA1 Git blob/tree
reconstruction and raw commit bytes, with no git subprocess or network. The
result proves that these bytes form the stated object, not that the object was
approved, signed, reachable on a remote branch or passed CI. Those claims remain
external integration evidence, never inferred from this reader.

## 2. Fixed physical layout and closed types

The bundle has exactly two top-level entries: source/ and installation/.
source/ contains the COMPLETE tracked Git tree, including scripts/, frontend/,
docs and non-Python files. No archive export-ignore/subst transformation is
permitted. There is no .git directory, symlink, gitlink/submodule or special file.
The Git archive compression/container is not validated here; the exact extracted
file tree is. Empty extra directories reject, except permitted caches below.

installation/ contains exactly these six regular one-link files:

- study-runtime.json: fixed locator
- study-runtime-readback.json: independent physical readback facts
- source-manifest.json: complete closed source inventory
- git-commit.bin: uncompressed raw Git commit-object payload, WITHOUT object header
- profile.json: original native profile bytes, opaque in this slice
- qualification.json: original native Q bytes, opaque in this slice

All bytes are read-only inputs. No mkdir, file creation, chmod, deletion, repair,
normalization write, SQLite, subprocess or socket operation is allowed. Missing
input never triggers a search, fallback or attempted package completion.

Canonical JSON is the existing Study encode/decode grammar: UTF-8, sorted keys,
compact separators, ensure_ascii=True, allow_nan=False, duplicate-key rejection,
raw==encode(parsed). Unknown keys reject at every specified object. Integers
reject bool. H is lowercase 64-hex SHA256; G lowercase 40-hex Git SHA1. Size is
integer >=1 unless manifest entry size (which may be zero). Bounds apply before
allocating/decoding large input: locator/readback <=2 MiB each, manifest <=16 MiB,
commit <=2 MiB, profile/Q <=1 MiB each, source file <=128 MiB, total tracked
source <=1 GiB, <=20000 tracked files, directory depth <=64, JSON depth <=16.
Source and artifact reads are chunked, with retained before/after identity and
size/mtime_ns/ctime_ns/nlink checks, not an unchecked read followed by a new
accepted baseline. Reject invalid UTF-8 where text is required; commit/source
file payloads are raw bytes.

Relative source paths are nonempty UTF-8 strings <=4096 encoded bytes, using /
only; no leading/trailing slash, empty component, ., .., NUL, CR, LF, backslash
or component named .git. Case and Unicode spelling are exact, never normalized.
Manifest entries must be unique by exact path and by physical file identity;
filesystem aliases/case folding cannot satisfy two entries. Walk each component
no-follow relative to retained directory FDs; targets must be regular nlink=1.

A directory binding is exactly {path,parent_chain,file_identity}. path is a
canonical absolute path (no URI, relative form, ., .., repeated/trailing slash,
NUL/CR/LF). parent_chain is the ordered array of [device,inode] from / THROUGH
the bound directory; file_identity equals its final pair. Device >=0/inode>=1,
non-bool integers. A file binding has exactly those keys plus sha256,size_bytes;
its parent_chain ends at its PARENT directory and file_identity names the file.
Physical bindings are local facts, not permission capabilities. All ancestors,
names, types, one-link identities and byte pins remain checked through exit.

## 3. Manifest and Git object verification

source-manifest.json schema is auto-g16-study-source-manifest/1, exactly
{schema,source_commit,source_tree,entries}. entries is a nonempty array, sorted
strictly by relative path UTF-8 bytes. Each entry exactly {path,mode,size_bytes,
sha256}; mode is the STRING 100644 or 100755. Record both content SHA256 and the
Git mode; the actual file execute bits must match: 100644 has no execute bits,
100755 has all three execute bits. Any setuid/setgid/sticky bit rejects. Read/
write permission bits do not establish authority and are not Git identity; a
read-only installed copy therefore need not become writable to match 100644.
All tracked paths with a __pycache__ component reject, so the cache exception
cannot hide a tracked entry. Directory entries are derived, never supplied.

For each file compute SHA256, exact size and Git object ID:
SHA1(b"blob " + ascii(decimal_size) + b"\0" + complete_file_bytes).
Construct every tree bottom-up. Each record is ascii(mode) + b" " + basename
UTF-8 + b"\0" + raw 20-byte child object ID. File modes use 100644/100755;
derived directory mode is 40000. Order entries by Git tree ordering: compare
basename UTF-8 with / appended for directories and no appended byte for files.
Hash SHA1(b"tree " + ascii(payload_size) + b"\0" + tree_payload).
The computed root MUST equal manifest.source_tree. Reject collisions between
file and directory names or any source entry not represented in the manifest.
SHA256 is retained in addition to Git SHA1; no cryptographic-signature assertion.

For git-commit.bin compute SHA1(b"commit " + ascii(payload_size) + b"\0" +
payload) and require manifest.source_commit. Require a header/message separator
b"\n\n" and first header line exactly b"tree " + source_tree ASCII. There
must be exactly one top-level tree header; a top-level header means a line not
starting with space. Other commit headers, signature continuation lines and
message are preserved as opaque bytes, never executed or interpreted as approval.
No parent traversal, author authentication or signature verification is claimed.
An annotated tag object is not a commit payload and rejects.

Mandatory tracked paths are auto_g16/__init__.py,
auto_g16/study/__init__.py, auto_g16/study/_installation.py,
scripts/run_v31_publisher_pilot.py and pyproject.toml. The implementation must
not count only a Python subset as a complete source archive. A package lacking
the scripts Controller cannot pass this contract even if an auto_g16 wheel exists.

Cache exception: an untracked __pycache__ directory may exist only immediately
inside a directory already implied by tracked paths. It must contain no
subdirectories/symlinks/special files/hardlinks, only regular files named
<stem>.<cache_tag>.pyc or <stem>.<cache_tag>.opt-1.pyc or .opt-2.pyc. cache_tag
must equal the current interpreter's nonempty sys.implementation.cache_tag;
<stem>.py must be a tracked sibling source file. Empty such directories are
allowed. Cap 3 files per matching tracked .py and 16 MiB per cache file. Do not
read or hash cache content and do not claim its correctness. Revalidate cache
name/type/containment at final inventory; benign additions/removals of qualifying
cache files are permitted, but no other unknown source file is ignored.

Ignoring pyc is NOT proof that loaded bytecode equals source: -B does not prevent
reading caches. This slice explicitly does not defend against malicious code
execution by the same-user installation principal, authenticate previously
executed Python code, or qualify cache trust. It returns executed_code_attested=false.
A later activation contract must bind the actual installed launch conditions;
it cannot turn this cache exception into a production code-identity bypass.

## 4. Locator and independent readback

study-runtime.json schema is auto-g16-study-installation-locator/1, exactly
{schema,source_commit,source_tree,source_manifest,commit_object,profile,
qualification,roots}. The four artifact values source_manifest,commit_object,
profile,qualification are file bindings to their fixed installation/ filenames;
any alternative path/basename rejects. source_commit/tree must match the fully
verified manifest and commit object. No arbitrary module, command, handler,
entrypoint, remote directory, environment or driver field exists.

roots is exactly {creation,runtime,registry}, each a directory binding to an
already existing local directory. The three roots must be distinct, pairwise
non-overlapping and physically unaliased; they must be outside bundle/ and
neither contain nor be contained in bundle/. The reader checks only these root
identities, not their contents or registry semantics. It creates/registers
nothing and makes no determination that any root is Owner-approved. Runtime
commands cannot replace them through arguments or environment. Selection of
actual values belongs to a separately reviewed installation, not this validator.

study-runtime-readback.json schema is auto-g16-study-installation-readback/1,
exactly {schema,bundle,source,installation,locator,source_commit,source_tree}.
The first three values are directory bindings matching this exact physical
layout; locator is the complete file binding for study-runtime.json. Commit/
tree equal the verified values. The readback is a separate immutable file whose
own binding is observed and returned, not embedded into its own payload. Locator
does not refer to readback, so no self-hash or cyclic digest is required.

Creation order for a later authorized installer is source/artifacts and roots
readback, then locator, then readback file. This contract implements no writer
and grants no authority for that sequence. A missing/partial readback is
installation-unavailable, never implicitly completed. A fully consistent forged
package is not distinguished from an approved one by this mechanical reader;
qualification_state remains not-assessed. Do not call the readback an acceptance
receipt or add a fabricated approved flag.

Profile and Q bytes are hash/size/physical-bound and retained, but their native
schemas and evidence semantics are NOT validated in this slice. They cannot
supply an alternate locator or source. Later native profile/Q validation must
consume exactly those bindings and bytes, not a path reopened without pins.

## 5. APIs, loaded paths and immutable lifetime

Only auto_g16.study._installation implements this boundary. Two context managers:

- inspect_bundle(bundle_directory): accepts one canonical absolute local path
  for offline package fact checking; no environment defaults. Does not claim the
  executing module was imported from that bundle.
- load_installed_runtime(): no arguments. Derives bundle root only from the
  actual module __file__, which must have exact suffix
  source/auto_g16/study/_installation.py. All components must already be canonical
  and no-follow; do not resolve a symlink into an accepted source path. No cwd,
  home/config search, sys.path manipulation, environment or setter is consulted.

The second entry additionally requires the actual loaded auto_g16 and
auto_g16.study package __file__ and import-spec origins to name their exact
tracked __init__.py paths under the same source/. Its own __file__/spec origin
must agree with the tracked _installation.py binding. These checks prove loaded
path consistency only, NOT code-object/pyc authenticity. It does not eagerly
import Controller/effect modules merely to check their paths; their full source
bytes are already inventoried. Native session qualification must later verify
its actual transitive loaded inventory and dependency runtime independently.

Both yield the same frozen facts dataclass with exactly:
{state,source_commit,source_tree,source_manifest_sha256,locator_sha256,
readback_binding,bundle_binding,roots,profile_binding,qualification_binding,
loaded_path_consistency,executed_code_attested,qualification_state,
execution_enabled}. state=mechanically-verified; loaded_path_consistency is
not-assessed for inspect_bundle and matched for load_installed_runtime;
executed_code_attested=false; qualification_state=not-assessed;
execution_enabled=false. Nested bindings/arrays are recursively immutable (no
mutable dict/list escaping). No live store, file FD, callback, driver, approval,
raw Q/profile bytes or callable effect capability escapes. The object represents
facts as of validated context exit; later use outside context grants no capability.
A stable installation fact ID, if needed later, must be a separately specified
derivative of these facts; this slice does not invent one.

Keep file/directory descriptors, exact byte identities and source inventories
held through the context. Recheck after the body and before release, including
all roots, metadata, tracked modes/content, and permitted cache inventory. Body
exceptions still release everything; retain the original exception and attach
only a sanitized error code if exit revalidation fails. Return/yield is not a
successful completed validation until exit checks succeed. No automatic retry.

For load_installed_runtime only, maintain one process-private binding cache and
nonblocking process lock. First successful full validation establishes the
immutable fact object, anchored to PID and exact physical/content identities.
First acquisition remains provisional until successful context exit; an exception
or failed exit publishes no first binding. Resource exhaustion fails closed,
releases acquired descriptors, and never raises system descriptor limits.
Subsequent calls revalidate the entire fixed package before yielding that SAME
object; no setter/rebind/reset API is exported. Changed facts or path identity
permanently invalidate production loading for that process, requiring a new
process and an independently reviewed installation. Failed first acquisition
must not cache a partial object. Forked inherited state rejects before any file
open; nested/concurrent loader contexts return busy. Body exception alone does
not erase/change an established binding; drift failure does poison it. Offline
inspect_bundle has no singleton installation effect and cannot seed this cache.

Use one private InstallationFactsError with exact code attribute from:
invalid-input, installation-unavailable, invalid-installation, source-mismatch,
identity-drift, busy, forked-process, installation-invalidated. Message equals
code only; no raw paths/probe content/exception text leaks. Missing file maps
unavailable; malformed schema/inventory/caps maps invalid-installation; wrong
Git/content hash maps source-mismatch; changed pinned metadata/path maps drift.
Public Study CLI error envelopes remain unchanged because neither API is wired
into executable run in this slice.

## 6. Required offline verification and later boundaries

Use tiny real synthetic Git-object fixtures, plus a complete locally available
source archive fixture; no network/git subprocess required by tested product.
Pin expected commit/tree using an independent test implementation or precomputed
known fixture values, not the production tree routine as its own oracle.

Required tests cover exact objects/modes and binary/zero-byte/Unicode files;
Git ordering of file foo.bar beside directory foo/; wrong blob/tree/commit,
missing/extra source, file-directory collisions, mode drift, symlink/hardlink/
gitlink rejection; duplicate/unknown fields, caps and invalid canonical bytes;
missing/partial metadata; readback/locator binding substitution and root overlap;
all reads and exit drift; descriptor release and original-exception retention.
Test allowed caches, foreign tag/stem/extension/subdirectory/symlink caches and
no cache content/authenticity claims. Test file replacement during final readback
against the pre-read baseline rather than accepting a new post-read baseline.

In a real separate Python process, import only from the synthetic installed
layout and call the no-argument loader; assert fixed origins and repeated object
identity. Wrong package origin, worktree/module-layout import, changed locator,
source mutation, alternate environment/cwd, nested/concurrent load, forked
inherited binding and offline-inspection cache contamination must reject or
have no selection effect as specified. Tripwire writes, SQLite, socket,
subprocess, registry/session/effect APIs and all _FIXED_* assignments. Preserve
prior failures and exact source hashes. No test may perform target qualification.

Passing this slice does not qualify the archive for execution. Still open:
actual authorized installer and its no-overwrite publication/readback workflow;
accepted source/CI provenance and actual launch/dependency/cache conditions;
exact Q acceptance and applicable new-source P08/target evidence; restricted
prepared-stage basis publication, preparation-observation scope, three approvals,
registry/session selectors, submit/collection and installed frontend integration.
Those are explicit subsequent contracts under the same authorized scope, not
permission inferred from mechanically-verified. Do not reuse old Q as new-code
qualification or introduce a signature service/new long-term trust framework.
