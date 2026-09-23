# Auto-G16 v3 acceptance: transport-launcher

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:1642-1881 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-TRANSPORT-SSH-CONFIG-EFFECT-SEAM-01 acceptance

1. Transport reuses the unchanged public `ServerProfile` and Execution
   resolver. The four exact path keys and four exact logical config names in
   `boundary-spec.md` are mandatory; missing, duplicate, aliased, or extra
   effect-configuration input fails before process creation.
2. Both SSH configs pass the closed UTF-8/LF, SP-only, case-sensitive,
   one-Host-stanza grammar. Exact physical-line, comment, blank, directive,
   value, and alias lexical rules and the allowed directive inventory are
   enforced. Include, Match/exec,
   ProxyCommand/ProxyJump, command hooks, forwarding, KnownHostsCommand,
   providers, agent overrides, wildcard/multiple Host values, quotes,
   escapes, and continuation reject.
3. Each config's dedicated absolute `IdentityFile` applies to the exact Host
   alias passed to SSH. `IdentitiesOnly yes`, `StrictHostKeyChecking yes`, and
   exact `UserKnownHostsFile` are present. Private-key bytes/digests are never
   read, logged, persisted, committed, or added to authority. Literal config,
   known-host, and identity paths reject `%`, `$`, `~`, wildcard/bracket/brace
   metacharacters, token expansion, and environment expansion.
4. Parsed Mac HostName/User/Port equals the sole snapshot RTwin hop. Parsed
   RTwin HostName/User/Port equals the snapshot destination. Missing port means
   exactly 22. A redirect, alternate destination, extra proxy hop, or stanza
   mismatch rejects before effect.
5. The outer command matches the complete ordered normative argv template and
   synthetic token vector. It uses exact manifest `mac_ssh`, exact bound `-F`, and
   explicit batch, identities-only, strict-host-key, no-agent,
   public-key-only, password-off, keyboard-interactive-off, GSSAPI-off,
   hostbased-off, host-key-DNS-off, and host-key-update-off options. Both
   user and global known-host options equal the same exact bound Mac file.
6. The PowerShell launcher invokes exact manifest `rtwin_ssh` with the complete
   ordered normative child argv, the same closed option set, exact RTwin `-F`,
   and the same bound RTwin known-host file
   for both user/global sources. Caller options, shell fragments, config paths,
   targets, and ambient defaults are impossible inputs. Its option terminator
   precedes the exact destination alias, and the exact child token vector uses
   the already-frozen CRT quote function plus one-SP joining.
7. Exact current profile resolution and complete snapshot equality precede
   configuration use. Config-byte, known-host-byte, path-key, resolved-profile,
   or effective-digest drift rejects before the first process.
8. A prelaunch missing, non-regular, symlink/reparse, size-mismatched,
   digest-mismatched, or replaced Mac config/known-hosts yields zero subprocess.
   Valid unchanged local files attest before and after process completion. A
   postlaunch drift rejects the result and preserves `UNKNOWN` if an effect may
   have crossed; it never retries.
9. A prelaunch missing, non-regular, reparse, size-mismatched, or
   digest-mismatched RTwin config/known-hosts yields zero nested server SSH. A
   postlaunch drift yields an unusable result/closed Transport error and
   preserves `UNKNOWN` where applicable; it never retries.
10. Existing nine-root executable trust, bootstrap protocol/table/source,
    resource enactment, workspace/artifact physical identity,
    `REPLAY` zero-qsub, and `UNKNOWN` zero-second-qsub tests remain PASS.
11. The product-level synthetic V30-A composition remains PASS. The repair
    changes no public upstream API/schema, creates no Attempt, and performs no
    SSH, RTwin, PBS, Gaussian, deployment, cleanup, or other live effect.
12. The old resolved profile identity remains failed evidence. A later live
    packet must create a new profile revision, resolved identity,
    ExecutionSnapshot, and Operational Confirmation before one fresh Attempt
    may cross a separately approved Live Owner Gate.

## V30-TRANSPORT-RTWIN-LAUNCHER-CHAIN-02 acceptance

1. The repaired path accepts only manifest logical name/schema v2 and exactly
   ten roots including exact source-controlled `rtwin_launcher`; manifest v1,
   nine roots, eleven roots, or launcher path/size/digest drift reject before a
   process.
2. The outer remote command records actual CMD boundary semantics, begins with
   exact explicit system PowerShell, contains one fixed loader, is strictly
   shorter than 4096 characters, and contains neither complete bootstrap nor
   manifest bytes. Raw PowerShell as the remote command rejects.
   The exact 1021-byte loader-template SHA and one-pass placeholder inventory,
   canonical value renderers, and exact command prefix/order are replayed.
   Percent and delayed-expansion exclamation forms reject before CMD.
3. The loader proves regular/non-reparse launcher identity before strict decode
   and before one ScriptBlock creation/invocation. Missing, replaced, reparse,
   size-drifted, digest-drifted, or invalid-UTF-8 launcher bytes yield zero
   nested SSH.
4. Exact bootstrap and manifest runtime paths come only from current resolved
   profile platform paths and their bytes only from runtime contents. Missing,
   aliased, latest/fallback, size/digest-drifted, reparse, or replaced runtime
   data yields zero nested SSH.
5. Outer stdin is exactly the AGV3 frame. Tests include binary NUL/high-byte
   forwarding and prohibit Reader/Writer/text conversion. The launcher uses a
   direct non-shell Process for `rtwin_ssh`, the frozen options and aliases,
   and an inner argument line shorter than 30000 characters. Output/error caps
   are enforced while draining each stream; overflow terminates and rejects
   rather than buffering through the cap.
   Controller and launcher independently agree on its exact character length
   and UTF-8 SHA-256 before Process creation.
6. The new bootstrap exact 15562-byte/203-LF/SHA identity passes Python 3.6
   grammar tests. Actual read-only qualification proves exact server Python
   3.6.8 identity, compile, startup, framing prerequisites, and no workspace
   operation. Historical `b0b1bcaf...` bytes remain failed-live evidence.
7. Protocol/table `/2`, exact seven operations, Torque and synthetic resource
   rendering, resource sole authority, workspace/artifact identities,
   `REPLAY` zero qsub, `UNKNOWN` zero second qsub, and synthetic V30-A
   composition all remain PASS.
8. The change uses no new public Core, Approval, Workflow, Execution, Observe,
   Result, ScientificValidation, or Review API/schema. TransportStore records
   successor runtime identities without schema migration.
9. Post-integration deployment publishes exactly three fresh no-overwrite
   files and changes no known-host, credential, policy, Attempt workspace, PBS,
   or calculation state. Qualification is read-only. No qsub, Gaussian, qdel,
   cleanup, deletion, retry, or replacement Attempt occurs.
10. ServerProfile revision 2 and all old operational approval objects remain
    unusable. A later live retry requires exact revision 3 resolution and a new
    Batch Submit Approval, ExecutionSnapshot, Operational Confirmation,
    submission-intent identity, and separately authorized recovery Attempt.

## V30-TRANSPORT-RTWIN-LAUNCHER-MULTILINE-BOOTSTRAP-QUOTING-REPAIR-01 acceptance

1. The generic launcher `Quote-Posix` behavior is byte-for-byte unchanged for
   ordinary values and still rejects NUL, CR, and LF. No caller, path, option,
   alias, user, manifest value, or arbitrary runtime content can select the
   fixed multiline route.
2. The dedicated fixed-bootstrap route accepts only the exact 15562-byte,
   203-LF, zero-CR/NUL bootstrap with SHA-256
   `ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae`
   after literal-path regular/non-reparse attestation and strict UTF-8
   decode/re-encode equality. Size/hash drift, one-byte mutation, invalid UTF-8,
   CR, NUL, or another runtime content rejects before quoting or nested SSH.
3. Literal LF and embedded single quotes round-trip exactly in one Python `-c`
   argv value. Dollar, backtick, semicolon, pipe, glob, substitution-looking,
   and newline characters remain literal data. Offline shell reconstruction
   yields exactly server Python, `-I`, `-S`, `-B`, `-c`, the original bootstrap,
   and the exact manifest argument; the reconstructed source compiles under
   the frozen Python 3.6 grammar.
4. The controller and successor launcher independently render the same inner
   CRT argument-line length and UTF-8 SHA-256. The existing strict
   30000-character inner bound is unchanged and PASS; crossing it rejects
   before a process.
5. The successor launcher is `auto-g16-v3-rtwin-launcher-v2.ps1`, 8576 bytes,
   140 LF, zero CR/NUL, SHA-256
   `1e6a82100cdcdffc258a0c29ab4d76d3d385b72565f5030806b19e3ea22f2d48`.
   The successor canonical manifest remains schema v2,
   protocol `/2`, and exactly ten roots, changing only the launcher trust-root
   identity required for the new bytes/path. The bootstrap source identity is
   unchanged.
6. ServerProfile revision 4 binds the successor launcher and manifest while
   preserving all other deployed/runtime/scientific/resource identities. It
   resolves a new ID and effective digest; revision 3 remains immutable and
   cannot authorize the successor.
7. Existing Transport focused/affected safety evidence and the synthetic V30-A
   composition remain PASS, including exact trust roots, binary AGV3 forwarding,
   workspace/artifact identity, qsub-at-most-once, REPLAY zero qsub, and UNKNOWN
   zero automatic retry.
8. Independent contract and implementation reviews report
   `P0/P1/P2/P3 = 0/0/0/0`; exact-main required checks and natural CodeQL
   attestation pass. No public upstream API/schema or bootstrap protocol
   semantics change.
9. Product integration performs zero RTwin persistent write, workspace/staging,
   qsub, Gaussian, qdel, cleanup, or Attempt creation. The exact successor
   launcher and manifest are only a proposed two-file deployment packet until
   a separate Owner deployment gate.

## V30-TRANSPORT-AGV3-EOF-INDEPENDENT-FORWARDING-01 acceptance

1. Revision-4 deployed bytes remain immutable; deployment stays PASS and the
   deadlocked read-only qualification stays failed evidence. No product test or
   integration step writes RTwin, starts nested real SSH, creates a workspace,
   stages an artifact, submits qsub, runs Gaussian, or creates an Attempt.
2. The successor launcher reads exactly one 12-byte AGV3 header and the exact
   declared payload, with maximum payload length 179306484, before nested SSH
   starts. It performs no JSON, operation, binding, or authority interpretation.
3. Bad magic, nonzero high length word/oversize, partial header, and partial
   payload all reach zero nested process. A bounded controller timeout may
   terminate an incomplete open stream; incomplete bytes never cross the seam.
4. A complete frame reaches the exact attested nested SSH process byte-for-byte.
   Bounded stdout/stderr drains start before the one finite asynchronous input
   write, so large bidirectional traffic cannot deadlock on pipe backpressure.
   Input completion and nested-stdin close do not wait for outer EOF. Tests with
   outer stdin held open prove the exact required ordering.
5. The launcher contains no synchronous request write before output drains,
   `ReadToEnd`, EOF-dependent `CopyToAsync`, line/text
   conversion, post-frame read, or trailing-byte authority. Controller tests
   prove its encoder emits exactly one complete frame with no prefix/suffix.
6. A one-byte full-length mutation is forwarded unchanged by the launcher and
   rejected by the unchanged bootstrap. The bootstrap retains exact frame,
   canonical JSON/schema/binding, and post-frame EOF checks.
7. Generic POSIX quoting still rejects LF; the exact fixed-bootstrap exception,
   inner command length/digest, pre/post trust-root and config attestation,
   binary stdout/stderr, Python 3.6 source, and ten-root manifest rules remain
   PASS.
8. Launcher identity is exactly
   `auto-g16-v3-rtwin-launcher-v3.ps1`, 9579 bytes, 161 LF, SHA-256
   `7247beda73482146c26b997702c9f74e6e9fb930e0bc55605fde42caa218658f`.
   A successor manifest-v2 instance and immutable ServerProfile revision 5
   bind new launcher/profile identities; protocol/table/bootstrap remain `/2`.
9. Focused Transport, affected selector evidence, and the changed synthetic
   V30-A composition path pass. REPLAY remains zero qsub, UNKNOWN remains zero
   second qsub, and all existing no-overwrite/physical-binding/Torque evidence
   remains intact.
10. Independent adversarial review reports `P0/P1/P2/P3 = 0/0/0/0`.
    Before later deployment/qualification, exact read-only reconciliation must
    prove the six prior residual processes are now count zero; otherwise the
    next gate is exact-process termination, not deployment.

## V30-TRANSPORT-WINDOWS-OPENSSH-REDIRECTED-OUTPUT-COMPLETION-CONTRACT-01 acceptance

1. Revision-5 deployment remains PASS, qualification remains failed evidence,
   and no test, PR, or integration action modifies or republishes its deployed
   files. No workspace, qsub, Gaussian, qdel, cleanup, retry, or Attempt is
   created.
2. The launcher recognizes completion only after exact `AGV3`, a bounded
   uint64 length, and all declared payload bytes. Partial header/payload, bad
   magic, oversize, stdout overflow, stderr, an extra byte, or a second frame
   can never reach the controlled-success branch.
3. After exact nested-stdin closure and response completion, bounded drains
   continue through an exact monotonic 5000-millisecond natural-exit grace.
   Natural exit/EOF remains valid. A still-live child may be terminated only
   through the exact `Process` instance created by the launcher; no broad,
   name-based, discovered, replacement, or process-tree termination exists.
4. After owned teardown, both streams close, captured stdout remains exactly
   one frame, stderr remains empty, every postlaunch attestation passes, and
   only then may the launcher return mechanical success. Kill failure, extra
   output, diagnostic output, or postlaunch drift fails closed.
5. Complete malformed JSON and exact complete frames carrying wrong protocol,
   operation, status, result, or binding pass no semantic authority. Existing
   Controller decoding rejects each vector. Merely receiving stdout never
   means success.
6. Bootstrap bytes/digest, request EOF validation, AGV3 `/2`, seven operation
   schemas, manifest schema v2, ten roots, operation table, public APIs, Torque
   renderer, workspace/artifact identities, and resource sole authority remain
   byte-for-byte or semantically unchanged as applicable.
7. Existing effect regressions remain PASS: `REPLAY` produces zero effect,
   `UNKNOWN` produces zero automatic retry/second qsub, qsub remains at most
   once, and no response-completion path can manufacture a Core claim or new
   effect authority.
8. Launcher identity is exactly `auto-g16-v3-rtwin-launcher-v4.ps1`, 11790
   bytes, 200 LF, SHA-256
   `52ce86be68356832b5b357c1c088aee9fc1b19701fe98115ef97b2a077dd7f60`.
   A successor manifest-v2 instance and ServerProfile revision 6 bind the new
   identity; bootstrap remains unchanged.
9. Focused Transport, affected selector evidence, and the changed synthetic
   V30-A composition path pass without any network/live test. Independent
   adversarial review reports `P0/P1/P2/P3 = 0/0/0/0`.
10. Integration authorizes only preparation of the exact revision-6 two-file
    deployment packet. Deployment, real qualification, recovery Attempt,
    approvals, snapshot, operational confirmation, and calculation effects
    remain separate Owner gates.
