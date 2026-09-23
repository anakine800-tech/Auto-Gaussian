# Auto-G16 v3 acceptance: transport-composition

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [V30-TRANSPORT-BOOTSTRAP-CHAIN-03: Deployment Manifest and Closed Command Chain](transport-bootstrap.md#v30-transport-bootstrap-chain-03-deployment-manifest-and-closed-command-chain)

<!-- Moved from docs/v3/acceptance.md:1026-1162 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-EXEC-02-COMPOSITION-CONTRACT-01: RTwin-First V30-A Composition

**Status: CLOSED / FROZEN / INTEGRATED.** The trust closeout below is the
active successor authority. The composition contract remains satisfied only
while all conditions below continue to hold:

1. The Controller completes pure `validate_effect_authority(...)` and every
   non-effect validation, does not call `record_submission_intent(...)`, and
   invokes the unchanged public `execute_once(...)` once.
2. `execute_once(...)` alone owns the Core claim. `WINNER` alone crosses the
   first effect boundary; `REPLAY` causes zero adapter, filesystem, transport,
   scheduler, and Gaussian calls.
   The official concurrency proof has two Controllers complete Approval replay
   while the Attempt is `PLANNED`, synchronize, then obtain exactly one
   `WINNER` and one `REPLAY`; the replaying port receives zero calls. A later
   Controller is rejected by Approval before Execution. Bypassing Approval for
   sequential replay is invalid composition.
3. The boundary is not described as a distributed transaction. Crash or
   ambiguity after `WINNER` cannot roll back the claim or authorize retry;
   possibly-effectful evidence yields `UNKNOWN` plus same-Attempt read-only
   reconciliation only.
4. V30-A is RTwin/PBS-first through an adapter implementing the unchanged
   `ExecutionPort`. OpenSSH, live RTwin/PBS/Gaussian, qdel/cancellation,
   cleanup, deployment, credentials, and remote smoke remain deferred.
5. The new package is exactly `auto_g16.transport`, future tests are under
   `tests/v3/transport/`, and no existing Core/Approval/Workflow/Execution/
   Observe/Result/ScientificValidation/Review API or schema changes.
6. The exact nine-symbol public inventory and every exact field/method
   signature in `boundary-spec.md` are closed. Public records are frozen,
   slotted, keyword-only, deeply immutable, and accept no raw command, shell,
   callback, arbitrary root, or caller-selected executable.
7. `ExactRemoteJobBinding.from_persisted_receipt(...)` accepts only the current
   snapshot, public `ReceiptJournal`, exact persisted receipt ID, current
   public `ServerProfile`, and the shared `TransportStore`. It resolves exact
   config, scans only the exact Attempt journal and matching Transport job/
   receipt rows, requires exactly one durable receipt ID, and rejects absent,
   duplicate, malformed, same-ID/different-payload, unpersisted/forged, store
   swap, or any Attempt/snapshot/intent/workspace/job/effect mismatch before
   read authority.
8. Scheduler acquisition is read-only, state/freshness is classifier-derived
   rather than caller-selected, and the exact qstat executable token, argv,
   workspace cwd, fixed environment, `shell=False`, timeout, byte caps, EOF
   requirements, present/not-found grammar, duplicate/malformed precedence,
   and Observe vocabularies match `boundary-spec.md`. Exact not-found is
   `absent`; command, transport, duplicate-record, or parse ambiguity is
   `unknown`; slow/running is not failure. Scheduler evidence grants no
   reconciliation, retry, or completion.
9. The Controller, not Transport, maps one exact scheduler record into public
   `AttemptObservation` and calls `record_attempt_observation(...)`. Transport
   never writes Core/Observe. Process acquisition remains deferred.
10. One fetch request is finite, non-empty, at most four entries, preserves its
    exact caller order without sorting/discovery, and is duplicate-free. It
    accepts only portable single-component allowlisted names; absolute,
    separator, dot/parent, shell, glob, symlink/reparse, recursive, and
    implicit-all-file requests fail closed.
11. Every fetched artifact proves the exact remote Attempt workspace, regular
    source stability across bounded before/read/after checks, exact immutable
    bytes/digest/size, and byte-return-only behavior. There is no local target
    or output write. Replacement, short read, drift, escape, per-artifact
    overflow, or aggregate overflow fails before returning truncated data and
    causes zero overwrite/cleanup.
12. A complete capture binds the full ordered request tuple, successful
    artifacts in exact order, and an empty missing partition. A partial capture
    has a non-empty exact successful prefix and the exact remaining request
    suffix as missing; interior holes, reorder, extras, duplicates, and zero
    stable artifacts reject. The Controller, not Transport, allocates sequence
    `1` or `max(Result envelope history) + 1`; Result rejects concurrent or
    conflicting sequence reuse. Transport performs no current/latest inference.
13. Transport schema-v1 UUIDv5 identities use the exact root/per-domain UUIDs,
    tagged canonical grammar, ordered arrays, manifest digest, and normative
    scheduler/capture vectors frozen in `boundary-spec.md`. Exact replay keeps
    identity; changed source bytes, binding, timestamp, sequence, status,
    completeness, request/missing partition, or artifact metadata changes
    identity; same-ID/different-payload conflicts.
14. `RTWinExecutionAdapter` requires one shared `TransportStore`, advertises
    `rtwin-pbs-v1`, and exposes only the unchanged `ExecutionPort` effect/
    reconciliation methods.
    `RTWinReadAdapter` exposes only exact scheduler read and exact output fetch,
    and both receive the already-attested persisted binding plus current public
    profile, revalidate snapshot/binding, publicly resolve the profile, and
    reject complete semantic/ID/effective-digest drift before every driver call.
15. Read adapter construction is non-effectful. It cannot submit, cancel,
    delete, clean up, mutate Core, resolve `UNKNOWN`, or create authority.
    Both adapters use the exact source-controlled operation table and exact
    resolved profile/runtime bindings. Tokens, argv, cwd, fixed environment,
    timeouts, byte caps, EOF, `shell=False`, and no-retry behavior are package
    authority; caller command text and secrets are impossible inputs. Table,
    executable, wrapper, and config identity drift rejects before a port call.
    Effect-side configuration remains owned by existing public
    `execute_once(..., current_profile=...)`; no private helper, global config,
    secret, or credential handle becomes authority/evidence.
16. The Controller verifies fetched bytes, builds public Result
    `OutputArtifact`/`OutputEnvelope`, and records through existing Result
    services. Transport does not import Result, create `ParseOutcome`, parse
    Gaussian bytes, select facts, or make scientific conclusions.
17. After Transport implementation is integrated, the separately gated
    test-local synthetic Controller proves the exact approval,
    Execution WINNER, scheduler Observe, fetch, OutputEnvelope,
    GaussianJobParser, ScientificValidation, ReviewBundle, and separate
    ScientificAcceptance chain without defining a product Controller API.
18. The legal concurrent composition produces exactly one Core `WINNER` and one
    `REPLAY`, with no calls through the replaying port. A later/preclaimed
    invocation fails pure Approval before Execution. A post-WINNER ambiguous
    submit yields durable `UNKNOWN` and no second qsub, child, alternative
    profile/workspace, or automatic retry.
19. The composition matrix rejects cross-Attempt, cross-snapshot,
    cross-receipt, cross-workspace, cross-job, capture/InputBinding, and Result
    provenance splices before downstream authority.
20. Network, subprocess, real qsub/qdel, Gaussian, unauthorized remote
    mutation, cleanup, and retry spies remain at zero in all contract and
    synthetic composition tests.
21. Reuse adjudication is complete: public v3 APIs are PORTed, narrow safety
    primitives/tests EXTRACTed, legacy RTwin running behavior WRAPped, typed
    boundaries REWRITTEN for the stated legacy-coupling reason, old governance
    DROPped, and OpenSSH/process/live capabilities DEFERred.
22. `V30-VAL-TRANSPORT-01` is integrated; Transport product/test paths route
    `affected / fail_closed=false`. No selector mutation or product
    implementation is included in this authority closeout.

The later implementation matrix must cover: exact persisted-binding happy path;
unpersisted forged receipt; absent/duplicate/malformed receipt; same receipt ID
with different durable payload; every binding-field mismatch; current-profile
exact replay and semantic/ID/effective-digest drift; operation-table/runtime-
binding drift; exact qstat argv,
cwd/env/shell/caps/EOF; scheduler queued/running/held/exiting/terminal/absent/
unknown; malformed and duplicate qstat; stable complete and partial fetch;
request traversal/symlink/replacement/short-read/digest/size/cap overflow;
exact prefix/suffix capture partition and sequence conflict; normative capture
and scheduler identity replay/conflict; Controller mapping equality; concurrent
`WINNER` exactly one call plus `REPLAY` zero calls; later Approval rejection;
post-WINNER ambiguity; same-Attempt reconciliation; full Result/parser/
ScientificValidation/Review chain; all cross-splice attacks; and zero live-call
spies.

V30-EXEC-02-COMPOSITION-CONTRACT-01 is integrated. It authorizes no product
Controller, OpenSSH, live work, or V30-A execution.
