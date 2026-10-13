# Auto-G16 bounded CREST loader closure

This proposed Q2-only delta follows the independent `crest_contract_review`
and parent runtime-boundary reviews. It does not change Q1 or its source bytes.
The helper is `auto_g16/execution/_crest_loader.py`, whose literal `_SOURCE`
is embedded byte-for-byte in the CREST probe and wrapper. Target acquisition
must use that same source, after independent review of its exact bytes.

Q2 runtime gains `crest_loader_closure`, schema `v31-crest-loader-closure/1`.
Its exact fields are `schema`, `host_key`, `root_object_id`,
`interpreter_alias_id`, `objects`, `aliases`, `needed_edges`, `selectors`,
`trace`, `loading_policy`, and `evidence_manifest_sha256`. This narrow version
qualifies one eligible host, Linux x86-64 little-endian ELF64. Kernel vDSO is
explicitly represented as a virtual kernel object under the existing host
kernel/namespace identity, not as a nonexistent on-disk library.

Objects are unique canonical paths with device/inode/size/SHA and exact ELF
class/endian/machine/type/PT_INTERP/NEEDED/SONAME/RPATH/RUNPATH metadata. Object
IDs hash those fields. Alias IDs hash requested path, full ordered lstat/readlink
component observations, canonical regular path and presence. Raw selected paths
retain `.`/`..` spelling; traversal handles these after symlink expansion rather
than normalizing away physical traversal semantics. Relative links
are expanded with finite bounds; their original text and each traversed node
remain recorded. Hash reads use O_NOFOLLOW final descriptors and before/after
identity checks. The root executable is hashed on the same held descriptor
passed to the loader trace. Symlink traversal here is solely read-only runtime
dependency interpretation; it grants no Project/Attempt mutation permission.

Every NEEDED ordinal has exactly one edge to an observed alias/object. Preserve
NEEDED and RPATH/RUNPATH order; canonical inventory sorting does not reorder
search semantics. Root, interpreter and the recursive reachable set must exactly
cover all actual loaded file objects. Cycles are allowed. Bounds reject excess
objects, aliases, depth, strings, data, unexpected trace lines and missing data.
Different NEEDED aliases may resolve to one object whose SONAME differs; retain
the SONAME without equating it to an alias. A NEEDED reference to the interpreter
may use its observed SONAME and unnamed trace record when physical identity
matches. ELF files are at most 256 MiB each, 64 objects and 512 MiB aggregate.

Use direct execution of the held root descriptor with only
`LD_TRACE_LOADED_OBJECTS=1` and `LD_DEBUG=libs`, no stdin, no shell and a 20-second deadline. Stream
stdout/stderr under one 262144-byte cap; exceeding it stops and reaps only this
diagnostic child. Reject setuid/setgid, file capabilities or unequal real/effective
identity; failure to acquire capability state is not absence. This
loader mode reports the actual static selection and exits before scientific
main. Its diagnostic environment introduces no library-path/preload override.
The scientific child retains the existing exact OMP_NUM_THREADS/XTBPATH
environment. The trace ignores ASLR addresses but retains actual names, paths,
ordering and the unique interpreter. This is an observed mapping, not a new
generic resolver implementation.

Selectors bind `/etc/ld.so.cache` and `/etc/ld.so.preload` as exact files or
final-component ENOENT with retained parent chain. Global preload is limited
to absent or an empty file. EACCES or another read failure never means absent.
Before any guard trace, recheck all fixed objects/aliases/selectors; drift means
zero diagnostic execution. Then the existing host guard runs the same bounded
observation and requires full equality before child execution and receipt
publication, followed by another fixed recheck. Initial qualification's outer
packet separately binds the already approved root ELF and trusted interpreter
before allowing the first trace. Repeating the actual
mapping detects a newly shadowing search-directory entry without inventing a
generic directory-resolution policy. The five existing host locations remain.

`loading_policy` is exactly CPU/internal-tblite, no optional plugin route, no
scientific LD overrides, the bounded direct trace policy, plus the independent
source/build/config review digest. The evidence-manifest digest binds retained
qualification evidence. These strings do not self-prove the policy: installed
binary/build evidence and the bounded calculator call path require review.
An optional bounded read of the matching CREST conda package metadata may supply
build provenance; its absence is recorded rather than replaced by a claim that
the installed binary was built reproducibly from the official tag.

The established trusted-host boundary remains. This finite observation does not
promise atomic immutability against concurrently acting trusted administrators,
audit all operating-system libraries, or prove arbitrary future dlopen routes.
Any unresolved dependency or use of an unreviewed optional loading path blocks
this qualification. No science, remote filesystem mutation or submission is
authorized by this document.

## Bounded deduplicated aliases and retained failure diagnostics

The same held-descriptor diagnostic retains complete stdout/stderr. Normalized
trace fields are `objects`, `kernel_objects`, and ordered `searches`; PID and
ASLR addresses are omitted from equality, while raw bytes remain qualification
evidence. Each search has a unique name and a closed sequence of typed search
phases and candidates. Unknown lines, duplicate names, nonzero namespaces,
multiple PIDs, unterminated blocks and any missing-library/error line fail.

Only an otherwise missing NEEDED name may use this narrow supplement. Its
unique complete search must contain exclusively bundled RPATH/RUNPATH phases;
cache, system/default and unknown phases reject that supplement. Every candidate
must be explained by its active printed directory list. The final candidate is
resolved through the complete alias walk and must equal exactly one object
already mapped by the same stdout trace, including canonical path, device,
inode, size, hash and ELF metadata. No new loaded object or synthetic stdout
record is inferred. Ordinary named trace mappings may still use system/cache
libraries. Recursive edges and before/after fixed rechecks remain mandatory.

This rule follows the independently reviewed glibc 2.17 source mechanism:
open_path returns upon success, object loading deduplicates device/inode, and
trace enumerates link_map first names. Cache lookup prints its own search phase.
This is a bounded supported grammar, not a target-vendor reproducible-build claim.

On failure the exception's `loader_diagnostics` retains phase, the exact pending
NEEDED source/name/ordinal when available, parsed partial trace, and raw trace
stdout/stderr with completeness/return status. Base64, SHA256 and byte counts
preserve exact raw bytes, including invalid UTF8; decoded text is display-only.
Guard comparison and postcheck failures carry the same retained diagnostics. Output-limit/deadline failures
retain bounded partial bytes. Acquisition wrappers must serialize these fields
on both success and failure; failed observations are never repaired in place.
Q2 installation retains both raw evidence-manifest and loading-review files as
fixed file bindings and typed evidence-index entries; a digest string alone is
not accepted as retained evidence.
