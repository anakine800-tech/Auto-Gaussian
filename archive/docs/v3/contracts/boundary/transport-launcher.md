# Auto-G16 v3 boundary: transport-launcher

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:4507-4778 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-TRANSPORT-RTWIN-LAUNCHER-CHAIN-02 current live-launch contract

Historical `transport-deployment-manifest-v1.json` remains a nine-root record
and is rejected by the repaired live seam. Current live-capable profiles use
exact runtime logical name `transport-deployment-manifest-v2.json`, schema
`auto-g16-v3-transport-deployment-manifest/2`, bootstrap protocol
`auto-g16-v3-rtwin-bootstrap/2`, and exactly these ten roots:

```text
mac_ssh mac_scp rtwin_ssh rtwin_scp rtwin_remote_shell rtwin_launcher
server_remote_shell server_python server_qsub server_qstat
```

The other eight historical roots retain their frozen roles. Manifest v2
intentionally reclassifies `rtwin_remote_shell`: it no longer claims to be the
Windows OpenSSH command boundary and instead binds the exact explicit
PowerShell child below CMD. `rtwin_launcher` is a Windows absolute-path
`rtwin-shell-file-v1` root with exact positive byte size,
lowercase SHA-256, null shell grammar, regular-file requirement, and
non-reparse requirement. Its fixed source identity is
`auto-g16-v3-rtwin-launcher-v1.ps1`, 7684 bytes, 125 LF, zero CR/NUL, SHA-256
`2eb539d4510988f892b52beeb743e088a27853cdfd9dc60ef0890978e0863444`.

Windows OpenSSH's actual boundary is CMD. `rtwin_remote_shell` binds the exact
explicit system PowerShell child and uses the sole closed grammar
`cmd-powershell-launcher-v1`; CMD is boundary grammar, not an eleventh trust
root. The complete remote command is exact PowerShell path, `-NoProfile`,
`-NonInteractive`, `-Command`, and one fixed loader string. It is shorter than
4096 characters and contains neither bootstrap source nor deployment-manifest
bytes. Injected values are exact current-authority paths, decimal sizes,
lowercase digests, and closed alias/port/user values only; CMD expansion and
metacharacter forms reject.

Manifest v2 is canonical JSON with exactly the four top-level keys
`bootstrap_protocol`, `deployment_id`, `schema`, and `trust_roots`. Every root
has exactly `attestation_mode`, `deployment_identity`, `expected_sha256`,
`expected_size_bytes`, `path`, `platform`, and `shell_grammar`; the existing
required/null rules apply, and no extension key is legal. The short loader is
the exact 1021-byte ASCII placeholder template with SHA-256
`e9417a66f6597791c519c403dd709a9bd791d516e3c421a1eb79cb6dc9fd0a47`.
Every named placeholder occurs once and is replaced once in sorted placeholder
name order. Paths/aliases/users use the frozen PowerShell single-quote grammar,
positive sizes/ports/lengths use unsigned canonical decimal, and digests use
lowercase 64-hex. The exact prefix/order is PowerShell path, `-NoProfile`,
`-NonInteractive`, `-Command`, then one double-quoted rendered template. No
alternate quoting, field order, omitted field, extra field, or caller fragment
is conforming.

The loader reads the literal launcher path, rejects container/reparse or
size/digest drift, strict-decodes the verified bytes as UTF-8, creates one
ScriptBlock from exactly those bytes, and invokes that in-memory block. Outer
stdin is not loader source: it remains exactly one byte-identical AGV3 request
frame from controller through outer SSH, launcher, nested SSH, and bootstrap.

The bootstrap and manifest are RTwin runtime data, not roots. Their only byte
authority is current `ServerProfile.runtime_contents`; their exact paths are
`platform_paths["rtwin_bootstrap_source_path"]` and
`platform_paths["rtwin_deployment_manifest_path"]`. Resolution requires two
distinct canonical Windows absolute paths, exact snapshot runtime identities,
and no latest, fallback, alias, or discovery. Launcher pre/post attestation
requires exact literal path, regular/non-reparse, size, and SHA-256.

The launcher has no generic operation surface. It may only attest the exact
RTwin SSH/SCP roots and bound RTwin config/known-hosts/runtime files, construct
the frozen nested SSH tokens, start manifest `rtwin_ssh` with
`System.Diagnostics.Process` and `UseShellExecute = false`, forward binary
stdin and output streams whose caps are enforced during each read, terminate
the child on overflow, reattest, and return the nested result. The
complete CRT-rendered inner argument line is strictly shorter than 30000
characters and is never routed through `cmd.exe`. Its exact character length
and UTF-8 SHA-256 are independently rendered by the controller and verified by
the launcher before Process creation.

The successor fixed bootstrap is logical name
`auto-g16-v3-rtwin-bootstrap-v2-py36.py`, 15562 bytes, 203 LF, zero CR/NUL,
SHA-256
`ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae`.
It has no `from __future__ import annotations`; complete source must parse for
Python 3.6 and compile/start under exact manifest-bound CPython 3.6.8 without a
workspace operation. Protocol/table `/2` and all seven operation semantics are
unchanged.

After normal integration, deployment may no-overwrite publish exactly three
identity-qualified RTwin files: launcher, bootstrap runtime data, and manifest
runtime data. Existing unexpected targets stop; no overwrite, cleanup, or
delete is permitted. Read-only qualification then proves actual
CMD-to-PowerShell parsing, verified launcher invocation, runtime attestation,
nested SSH startup, exact server Python 3.6.8, compile/start prerequisites, and
binary forwarding without `ALLOCATE_WORKSPACE`, staging, qsub, or Gaussian.
Only a new ServerProfile revision 3 and new operational authorities may be used
by a later separately approved recovery Attempt.

## V30-TRANSPORT-RTWIN-LAUNCHER-MULTILINE-BOOTSTRAP-QUOTING-REPAIR-01 boundary

The revision-3 launcher and manifest are immutable deployed history. The
successor launcher is the version-qualified
`auto-g16-v3-rtwin-launcher-v2.ps1`, 8576 bytes, 140 LF, zero CR/NUL, SHA-256
`1e6a82100cdcdffc258a0c29ab4d76d3d385b72565f5030806b19e3ea22f2d48`.
Its manifest remains
schema `auto-g16-v3-transport-deployment-manifest/2`, protocol
`auto-g16-v3-rtwin-bootstrap/2`, and exactly the existing ten trust roots. A
new canonical manifest content identity changes only the `rtwin_launcher`
path, deployment identity, size, and digest required by the successor.

The ordinary PowerShell `Quote-Posix` function remains the sole renderer for
dynamic tokens and rejects NUL, CR, and LF. One separate
`Quote-PosixFixedBootstrap` function may receive only `$Bootstrap` produced by
this closed sequence:

1. read the literal current-profile bootstrap path as bytes;
2. require regular/non-reparse identity, exactly 15562 bytes, and SHA-256
   `ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae`;
3. decode those exact bytes with strict UTF-8;
4. encode the decoded value with the same strict UTF-8 instance and require
   byte-for-byte equality with the attested input;
5. reject NUL or CR, permit literal LF, and replace every single quote with the
   POSIX single-quote boundary sequence;
6. surround the result with one single-quoted boundary and use it exactly once
   as the Python `-c` word.

Arbitrary caller text, another runtime content, or a value that has not passed
that exact identity gate cannot enter the fixed-bootstrap function. Dollar,
backtick, semicolon, pipe, glob, substitution, and literal LF characters inside
the attested value remain data inside the one shell word. They never become a
second command, word, expansion, or quoting policy.

The nested command remains exactly server Python, `-I`, `-S`, `-B`, `-c`, the
one fixed multiline bootstrap word, and the canonical base64 manifest word.
The controller's existing Python renderer and the PowerShell launcher must
produce the same exact CRT argument-line character length and UTF-8 SHA-256;
the existing strict 30000-character bound is unchanged. AGV3 framing, seven
operations, response semantics, binary stdin forwarding, caps, and pre/post
attestation are unchanged, so protocol/table `/2` do not advance.

Revision 4 is a new immutable ServerProfile revision. It binds the successor
launcher path and successor manifest-v2 path while reusing the exact revision-3
bootstrap path/bytes, SSH config, known-hosts, server Python, qsub, qstat, and
resource descriptor. It resolves a new profile ID/effective digest. Revision 3
and its deployed files remain historical and are not overwritten, deleted, or
cleaned. The repair integration prepares, but does not authorize, one future
fresh two-file no-overwrite deployment of launcher plus manifest.

## V30-TRANSPORT-AGV3-EOF-INDEPENDENT-FORWARDING-01 boundary

The revision-4 launcher, manifest, bootstrap, and profile identities are
immutable historical evidence. Deployment passed; the subsequent read-only
qualification failed because the launcher made nested-stdin closure depend on
outer EOF while the unchanged bootstrap required EOF after its one exact AGV3
frame. This section supersedes only that forwarding sequence.

The successor launcher performs one closed mechanical acquisition before any
nested process exists:

1. read exactly 12 bytes from outer stdin;
2. require bytes 0..3 to equal ASCII `AGV3`;
3. decode bytes 4..11 as one unsigned 64-bit big-endian length;
4. require the declared payload length to be at most 179306484;
5. read exactly that many payload bytes and nothing afterward.

It does not decode canonical JSON, inspect `protocol`, `operation`, `binding`,
or `payload`, select an executable, or create authority. A high 32-bit length
word is necessarily above the frozen cap and rejects. A short header or short
payload reaches no nested process. If a producer neither completes the frame
nor closes stdin, the existing controller deadline may terminate the outer
process; no partial frame may cross into nested SSH.

Only after the complete frame is resident does the launcher create and start
the one exact attested `rtwin_ssh` process. It starts the existing bounded
stdout/stderr asynchronous drains before one finite asynchronous write of the
exact header and payload bytes. All three tasks share the bounded completion
pump; when the finite input task completes, the launcher flushes and closes
nested stdin immediately while output drains continue. This prevents a child
that emits output before consuming a large request from deadlocking against a
synchronous write. It never uses
`ReadToEnd`, `CopyToAsync` through EOF, line/text conversion, a post-frame read,
or an outer-EOF wait. The required ordering is:

```text
FULL_FRAME_ACQUIRED < NESTED_SSH_STARTED
NESTED_SSH_STARTED < NESTED_FRAME_WRITE_COMPLETE
NESTED_FRAME_WRITE_COMPLETE < NESTED_STDIN_CLOSED
```

Nested-stdin closure does not read, observe, or wait for outer EOF. In the
required held-open proof vector, closure precedes the producer's later
deliberate EOF. A conforming controller may instead close immediately after
its one frame, so no universal event order is imposed on EOF. The bootstrap
still reads its own 12-byte header and exact payload, then requires one
additional read to return EOF; that check is not weakened. The Controller
still serializes exactly one frame with no prefix/suffix. Consequently a
full-length mutation passes the launcher mechanically but fails at the
bootstrap's existing canonical protocol/binding validation.

The source-controlled successor is
`auto-g16-v3-rtwin-launcher-v3.ps1`, 9579 bytes, 161 LF, zero CR/NUL,
SHA-256 `7247beda73482146c26b997702c9f74e6e9fb930e0bc55605fde42caa218658f`.
Bootstrap protocol/table/source and manifest schema stay `/2`; only a new
manifest-v2 content instance changes to bind the new launcher identity/path.
A future live chain must create immutable ServerProfile revision 5 and resolve
new `resolved_server_profile_id` and `effective_config_sha256` values. No
revision-4 object may be refreshed in place.

Before future deployment or read-only qualification, the six residual
launcher/nested processes reported by the failed qualification must be
reconciled by exact identity and count. Count zero is mandatory. A nonzero
count requires a separate exact-process termination gate; this contract grants
no broad kill, cleanup, deletion, or deployment authority. It also grants no
workspace/staging, qsub, Gaussian, retry, recovery Attempt, or live effect.

## V30-TRANSPORT-WINDOWS-OPENSSH-REDIRECTED-OUTPUT-COMPLETION-CONTRACT-01 boundary

Revision-5 deployment remains PASS and its deployed launcher/manifest remain
immutable. Production qualification remains failed evidence because exact
Windows OpenSSH 9.5p1 returned emitted bytes through redirected stdout/stderr
but kept the owned child process nonterminal. This section supersedes only the
nested response-completion rule. It does not authorize a revision-5 replay or
alter any deployed file.

The launcher mechanically recognizes response completion in this exact order:

1. collect at least the 12-byte response header under the existing
   179306496-byte stdout cap;
2. require bytes 0..3 to equal ASCII `AGV3`;
3. decode bytes 4..11 as one unsigned 64-bit big-endian length;
4. require that length to be at most 179306484;
5. collect exactly `12 + length` bytes;
6. require zero stderr bytes and zero stdout bytes beyond that exact frame.

No earlier state is response-complete. Partial header/payload, bad magic,
oversize, stderr, cap overflow, extra byte, or second frame rejects. A full
frame does not mean protocol success: the launcher parses no JSON and assigns
no operation, binding, status, result, retry, scheduler, or scientific
authority.

After both `NESTED_STDIN_CLOSED` and `RESPONSE_FRAME_COMPLETE`, a source-fixed
monotonic 5000-millisecond grace begins. Throughout the grace the existing
bounded asynchronous drains continue, so late extra output or stderr rejects.
If the child exits naturally, both streams must still reach EOF and the exact
child exit status is preserved. If it remains alive after the grace, only the
exact `Process` instance that this launcher created may be terminated. The
launcher then waits for that exact process and both pipes to close, rejects any
new bytes, and performs every existing postlaunch attestation before emitting
the buffered response. The owned-teardown mechanical outcome maps to launcher
exit zero only after those predicates pass. There is no process discovery,
PID-only lookup, name filter, tree kill, substitute process, or retry.

The Controller remains the sole response semantic authority. Its existing
decoder requires the exact frame length and canonical JSON, exact `/2`
protocol, matching operation, closed status/result schema, and operation-
specific binding. A malformed or semantically wrong complete frame therefore
fails after mechanical transport completion. For a possibly-effectful request,
anything short of one Controller-accepted response retains `UNKNOWN` and zero
automatic retry; it never permits a second qsub.

The unchanged bootstrap still reads one complete request and requires request
EOF. Its response bytes, AGV3 `/2`, seven operations, manifest schema v2, ten
trust roots, command construction, resource enactment, no-overwrite rules,
physical identities, and all public APIs remain unchanged. General process
completion/EOF rules elsewhere remain binding; this exception applies only to
the attested revision-6 RTwin launcher and its one owned nested Windows
OpenSSH child after an exact response frame.

The successor is `auto-g16-v3-rtwin-launcher-v4.ps1`, 11790 bytes, 200 LF,
zero CR/NUL, SHA-256
`52ce86be68356832b5b357c1c088aee9fc1b19701fe98115ef97b2a077dd7f60`.
Bootstrap identity remains 15562 bytes and SHA-256
`ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae`.
A successor manifest-v2 content instance changes only the launcher identity
and path; ServerProfile revision 6 must resolve a new profile ID and effective
digest. Integration prepares, but does not authorize, its fresh two-file
no-overwrite deployment.
