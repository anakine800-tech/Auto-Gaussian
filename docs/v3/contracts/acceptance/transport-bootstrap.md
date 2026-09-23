# Auto-G16 v3 acceptance: transport-bootstrap

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [`V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01`](transport-resources.md#v30-exec-resource-enactment-contract-01)
- [`V30-PBS-TORQUE-DIALECT-01`: exact production Torque renderer](transport-resources.md#v30-pbs-torque-dialect-01-exact-production-torque-renderer)

<!-- Moved from docs/v3/acceptance.md:1163-1390 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-TRANSPORT-BOOTSTRAP-CHAIN-03: Deployment Manifest and Closed Command Chain

**Status: FROZEN CANDIDATE; IMPLEMENTATION NOT AUTHORIZED BY THIS DOCUMENT.**
When this exact authority content is present on authoritative main after
independent review, the task is `CLOSED / FROZEN / INTEGRATED` and offline
Transport implementation is gate-eligible. Acceptance requires:

1. The only new public symbol is `TransportStore`; its explicit create/open
   methods require both `path` and keyword-only `approved_root`, its `close()`
   lifecycle plus both adapter constructor signatures exactly match
   `boundary-spec.md`. `ExactRemoteJobBinding` adds exactly
   `transport_store_id` and `store_instance_id`; no generic public SQL/token/
   authority API appears.
2. The store is Transport-owned, independent SQLite schema v1. Core and
   Execution schemas/APIs remain byte-unchanged; the store alone grants zero
   Core transition, receipt, effect, read, retry, or scientific authority.
3. Create and reopen require an independently supplied approved root, require
   the store path to be its strict descendant, walk from that descriptor
   no-follow, and reject parent/terminal symlink or reparse, non-regular
   targets, path/root/
   parent-chain replacement, unexpected schema objects, missing append-only
   triggers, malformed rows, wrong application/user/schema identity, and file
   identity drift without pathname fallback or overwrite.
4. The exact six-table schema, constraints, foreign bindings, append-only
   triggers, meta identity, and PRAGMAs equal the frozen contract.
5. Store, store-instance, runtime, workspace, artifact, job, and receipt-binding
   UUIDv5 identities use the exact seven domains and complete canonical arrays.
   Exact replay is
   idempotent; same-ID/different-payload and natural-binding conflicts leave the
   database unchanged and fail closed.
6. Trigger suppression, trigger mutation, zero-row insert, multi-row insert,
   schema reopen drift, and durable conflict after reopen all reject.
7. A workspace row binds exact Attempt, snapshot, submission intent, logical
   remote workspace, runtime attestation, and non-empty opaque physical token.
   Process restart cannot erase or substitute that authority.
8. Fresh allocation starts from the approved-root descriptor, walks/creates
   descriptor-relative and no-follow, rejects existing/replaced/symlink/escape
   targets, and persists a token only after stable final reattestation.
9. Every stage, qsub, qstat, reconciliation, and fetch loads the exact persisted
   workspace token and the remote agent reattests it descriptor-relatively
   before operation. There is no check-then-pathname fallback.
10. Each exact staged artifact is fresh/no-overwrite, verified by exact bytes,
    digest and size, assigned a post-write physical token, persisted, and
    reattested before qsub. Either token replacement or cross-workspace splice
    prevents qsub.
11. Job authority is append-only and unique per physical workspace. The later
    receipt-binding row can be created only from the exact public durable
    confirmed receipt and exact job/workspace record. Receipt replay is
    idempotent; mismatch or store swap rejects read authority.
12. A store failure after a possibly effectful allocation/stage/qsub remains
    possibly effectful/`UNKNOWN`; it never retries the operation, re-arms the
    Attempt, changes workspace, or creates cleanup authority.
13. Generated output fetch uses the persisted workspace token and one
    operation-local reattested read token with stable bounded bytes; evolving
    output is not inserted into the staged-artifact table. Cross-Attempt,
    cross-snapshot, cross-job, cross-workspace, replacement, short read, digest
    drift, or hidden latest/current selection rejects.
14. The only deployment-manifest source is exact current-profile runtime content
    `transport-deployment-manifest-v1.json`. Public profile resolution, complete
    snapshot resolved-profile equality, and exact `runtime_identities` byte
    identity all pass before parse or driver call. No parameter, alias, global,
    fallback, or latest/current manifest exists.
15. Manifest bytes satisfy the exact UTF-8 canonical JSON plus one-LF grammar,
    exact four-key top level, exact constants, non-empty deployment ID, exact
    seven-key entry shape, and complete nine-root name/mode/platform/digest/
    size/grammar matrix. The 2753-byte normative vector and its SHA-256/runtime
    identity replay exactly.
16. Deployment/OS and that manifest are final pre-start authority. Configured
    RTwin and server remote shells plus `server_python` do not authenticate
    themselves before interpreting/starting; later checks detect drift only.
17. The real command chain includes both remote shells. Local `shell=False`
    removes only a local shell. Manifest selection is exactly `powershell-v1`
    or `cmd-v1` plus server `posix-sh-v1`; unknown, inferred, or fallback grammar
    fails closed.
18. `powershell-v1` uses exact literal-path type/reparse/size/SHA checks and the
    frozen ProcessStartInfo/CRT structured launcher. `cmd-v1` token quoting is
    exact but its nine-root compatibility check deterministically rejects before
    RTwin child launch because no trusted SHA-256 primitive exists. No tenth
    helper root appears silently.
19. The fixed runtime content `auto-g16-v3-rtwin-bootstrap-v1.py` runs only
    under exact manifest `server_python` with fixed `-I -S -B -c`. For all
    seven operation enums, the exact request top-level, binding, and payload
    key sets plus the exact response top-level/result schemas and conditional
    cardinalities match `boundary-spec.md`; no implementation must invent an
    authority field. The four normative allocate/fetch JSON byte vectors,
    sizes, digests, operation/protocol echo, padded base64, and negative schema
    matrix replay exactly. Caller source, module, executable, command, shell
    fragment, generic operation, extra bytes, or missing EOF rejects.
20. After deployment-trusted start, `server_python` may detect self drift and
    attest exact absolute qsub/qstat path/type/size/digest before structured argv;
    those checks never establish pre-start trust. Mac executables are directly
    attested; RTwin executable attestation is owned only by the declared shell.
    Prelaunch drift gives zero call and postlaunch effect ambiguity gives
    `UNKNOWN` without retry.
21. Each request is one bounded AGV3 frame on stdin and each accepted response
    is one bounded AGV3 frame on nested-process stdout; there is no unspecified
    binary side channel. Bootstrap stderr is capped diagnostic-only and must be
    empty for an accepted response. Exact per-operation stdin/stdout caps cover
    stage/fetch base64 expansion and qstat inner-stream expansion. Overflow,
    extra/multiple frames, authority data on stderr, truncation, timeout,
    malformed completion, or ambiguous qsub produces fail-closed/`UNKNOWN`
    behavior with zero retry.
22. The physical-binding envelope uses the exact seven-operation table v1,
    1490-byte canonical vector and digest. It changes neither the unchanged
    public `ExecutionPort` nor receipt APIs and is data evidence, not a
    capability or approval mechanism.
23. Concurrent Controllers still yield at most one `WINNER` and at most one
    qsub; `REPLAY` makes zero port/driver calls. All pure Approval failures
    remain before claim/effect.
24. RTwin-first, Result-owned Gaussian parsing/capture, Observe read-only
    projection, and the full synthetic composition requirements remain intact.
    Transport performs no raw scientific interpretation.
25. `V30-VAL-TRANSPORT-01` remains active with `affected / fail_closed=false`;
    exact scope is the five authority files and there is no selector, product,
    test, context-map, deployment, or live mutation.
26. OpenSSH, process/Gaussian-phase acquisition, qdel, deletion, cleanup,
    deployment, automatic retry, and every live RTwin/SSH/PBS/Gaussian effect
    remain deferred.
27. Threat-model tests explicitly prove ordinary clone/move/alias/replacement
    rejection while documenting that malicious same-UID/root/kernel/filesystem/
    deployment compromise is excluded and uncloneability is not claimed.
28. Create-new uses one non-caller-selectable 32-byte OS-CSPRNG nonce; reopen
    preserves it. Exact logical store ID and physical instance ID bind approved
    root/path, file identity, and parent chain and appear in meta, every store
    record, `ExactRemoteJobBinding`, scheduler identity, and capture identity.
29. The exact store/store-instance and five evidence-domain canonical arrays,
    namespace UUIDs, nonce/file/parent fixture, canonical byte vectors, and
    UUID outputs match `boundary-spec.md`. The superseded abbreviated executable
    fixture and dependent IDs reject; the complete nine-root manifest and active
    manifest-bound identity vectors pass.
30. Wrong manifest name; missing manifest/root/field; extra root/field; wrong
    schema/protocol/platform/mode/grammar; duplicate JSON key; BOM; noncanonical
    JSON; missing/extra LF; NaN/Infinity; bad SHA; bool/zero/negative size;
    relative path; profile drift; changed post-snapshot bytes; or runtime identity
    mismatch all reject before any process call.
31. PowerShell literal/quote/CRT round trips cover empty, spaces, apostrophes,
    backslashes, metacharacters, and NUL/CR/LF rejection. Cmd safe-token quoting
    and forbidden-token tests end in deterministic deployment incompatibility,
    never PowerShell/certutil/bridge fallback. POSIX variable-token vectors
    reject NUL/CR/LF, while the separate fixed-source vector preserves LF and
    rejects NUL/CR; both replay exactly as one shell word.
32. TransportStore runtime rows bind the exact manifest name/identity,
    deployment ID, bootstrap protocol, operation table, bootstrap source,
    resolved profile and snapshot; linked rows reject cross-profile/deployment
    replay. The store remains physical evidence, not manifest authority.
33. Reuse adjudication remains explicit: append-only SQLite/path primitives are
    PORTed/EXTRACTed; existing RTwin operation mechanics remain WRAPped; store,
    physical-binding and data-only protocol glue are REWRITTEN because legacy
    code couples them to v2 governance/dynamic command behavior; owner/
    capability/hash-currentness/retry/cleanup are DROPped; native wrapper,
    OpenSSH, deployment and live are DEFERred.
34. Exact scope remains the five authority files, worktree is clean, and fresh
    independent adversarial review reports `P0/P1/P2/P3 = 0/0/0/0` before
    publication.

Mandatory adversarial evidence includes all prior Transport and composition
tests plus store path/schema/trigger/reopen conflict; workspace and artifact
replacement across process restart; forged/stale/cross-store tokens; first-
append and receipt-binding conflicts; CSPRNG/non-caller nonce; clone/move/
hardlink/parent-chain replacement; cross-store IDs in scheduler/capture;
dynamic-agent/module/eval/exec upload spies; bootstrap self-attestation absent;
complete nine-root manifest plus every manifest negative in condition 30;
current-profile/snapshot/runtime-identity closure; configured PowerShell path/
type/reparse/size/digest drift; cmd incompatibility without fallback; exact
server shell/bootstrap source/frame/operation enum; exact seven request-binding/
payload and response-result schemas; all conditional stat/reconciliation
cardinalities; allocate/fetch wire vectors; missing/extra/wrong-type keys;
base64/size/digest/token/EOF mismatch; qsub/qstat drift; Windows CRT,
PowerShell, cmd, POSIX variable-token, and fixed-source quote vectors; pre/post
launch replacement; bounded
stdin/stdout/diagnostic-stderr and EOF failures; extra/multiple response frames;
`UNKNOWN` without retry; and zero tenth-root/native-wrapper/live/qdel/delete/
cleanup spies.

## `V30-TRANSPORT-BOOTSTRAP-SOURCE-CLARIFY-01`

This narrow clarification is accepted only when all of the following hold:

1. Variable POSIX launcher tokens reject NUL, CR, and LF before command
   construction; empty tokens and literal apostrophes still round-trip through
   the frozen single-word encoder.
2. The fixed protocol-owned bootstrap source is not treated as a variable
   token. It accepts ASCII LF, rejects NUL and CR, and round-trips as exactly
   one POSIX argv element with byte-for-byte source equality.
3. The normative 12-byte source-quoting fixture, its exact 18-byte quoted
   form, both SHA-256 values, and the full 13904-byte production-source
   round-trip match `boundary-spec.md`.
4. The production source is exact ASCII
   `auto-g16-v3-rtwin-bootstrap-v1.py`: it begins and ends with the frozen
   bytes, contains 190 LF and zero CR/NUL, has size `13904`, and has SHA-256
   `056e27cab0a00e305c5e5acc7f5673e7d196dd0dc27516c31ec2cb95d6b58952`.
   Any source-byte, line-ending, size, or digest drift rejects.
5. The superseded `b`-repeated digest/`2048` source fixture and the prior
   12540-byte/170-LF source identity with SHA-256
   `724869c6767c1570075812832d57c94e8c9e17ae2d4cd1d9f8781b0796671d2f`
   reject. The active runtime, workspace, artifact, job, and receipt canonical
   vectors and UUIDs recompute from the exact production-source identity, and
   both source-dependent request wire vectors match their revised digests.
6. No manifest/profile/operation/caller value is interpolated into the fixed
   source or Python `-c` argument. Mutable operation data enters only through
   the one bounded canonical AGV3 stdin frame.
7. Attempts to insert LF into a variable path, manifest field, filename,
   operation, option, or argv value reject; attempts to use source LF as a
   command separator, add a second argv element, or append shell text reject.
8. Caller source/module/eval/exec, generic operation, alternate source,
   source fallback, CRLF normalization, missing/extra source LF, and a second
   mutable channel all reject without process/effect authority.
9. All previously frozen manifest, shell-chain, TransportStore, physical
   binding, WINNER, RTwin-first, OpenSSH-deferred, no-retry/qdel/delete/
   cleanup, upstream API/schema, and no-live decisions remain unchanged.
10. The candidate changes exactly `OWNER_DECISIONS.md`,
    `docs/v3/boundary-spec.md`, and `docs/v3/acceptance.md`; lightweight
    authority checks pass and fresh independent review reports
    `P0/P1/P2/P3 = 0/0/0/0` before publication.
11. Bootstrap protocol remains exactly `auto-g16-v3-rtwin-bootstrap/1` because
    the AGV3 framing, seven request/response schemas, operation table, and
    trust semantics are unchanged. The 13904-byte successor only implements
    already-frozen cap and postlaunch-attestation behavior; it adds no
    operation, channel, trust root, or caller-controlled source authority.

The `/1` conditions above remain immutable historical acceptance evidence.
For an executable resource-enactment successor, protocol/table/source `/2`,
the exact four-content runtime closure, and the `/2` qsub schema/vector in
`boundary-spec.md#snapshot-derived-pbs-resource-enactment` supersede only the
corresponding `/1` protocol-specific conditions. All retained trust, physical
binding, cap, no-shell, WINNER/REPLAY/UNKNOWN, and no-retry conditions continue
unchanged.
