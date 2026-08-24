# Auto-G16 v3 Owner Decisions

These decisions close the design questions accepted in Phase 0 and Phase 0.6.
They govern v3 planning until changed by a later reviewed Git commit.

## OD-01: Clean core and compatibility

v3 deliberately breaks v2 runtime compatibility. It is a clean-core,
selective rewrite: reuse is decided capability by capability, and preserved
data does not imply preservation of the v2 runtime ABI.

## OD-02: Semantic approval and edited inputs

Approval applies to the current `CalculationPlan` and its displayed meaning.
Manual editing of an input file is valid. After an edit, the controller must:

1. parse the current file again;
2. display the semantic diff;
3. obtain approval for the current `CalculationPlan`.

A hash may record artifact identity, but it is not a lock on an earlier
approval. v3 does not add a new hash-bound owner-approval mechanism.

## OD-03: Mutable profiles and execution snapshots

`ServerProfile` is mutable configuration. Every execution produces an
`ExecutionSnapshot` that captures the effective execution inputs for that
run. Review targets current semantics; the snapshot records what was used.

## OD-04: Project reuse and the no-overwrite boundary

An existing `Project` directory may continue to be used. The no-overwrite
boundary is a new `Attempt`; it does not require the entire `Project` to remain
forever fresh. A new execution must allocate a new `Attempt` and must not
overwrite a prior attempt's artifacts.

## OD-05: Single submission and uncertainty

Each `Attempt` may invoke `qsub` at most once. An ambiguous submission becomes
`UNKNOWN` / `submission_uncertain` and enters reconciliation. It must never be
retried automatically.

## OD-06: Transport targets

Direct SSH remains the long-term v3 transport target, implemented behind a new
thin `OpenSSHTransport`. It does not inherit the old single-use capability or
private owner-chain architecture. V30-A closes the first real composition with
an RTwin-first adapter over the already reviewed execution port; OpenSSH is
explicitly deferred until a later Owner gate. The legacy RTwin path remains an
adapter and reuse source rather than v3 authority. Live deployment always
requires separate, explicit authorization.

## OD-07: Safety semantics and governance implementation

v3 keeps reviewed execution-safety semantics while separating them from the
old governance implementation. Safety requirements are expressed at the v3
core and boundary level; the old governance machinery is not the v3
architecture.

## OD-08: Runtime and change-aware CI

The controller requires Python 3.11 or newer. Python 3.13 is the primary
full-validation runtime. Python 3.11 and 3.12 run compatibility and affected
tests by default instead of duplicating the complete full suite. CI is
change-aware and expands only when the affected surface requires it.

## OD-09: Conformer policy must be benchmarked again

v3 may extract existing conformer-science primitives, but sampling, coverage,
and DFT policy must be benchmarked again. Historical A/B route quotas are not
permanent scientific rules.

## OD-10: Approval authority is separated into three gates

v3 separates scientific meaning, permission to submit selected Attempts, and
effect-time confirmation. They are three different authorities:

```text
CalculationPlan
    -> Scientific Approval
    -> Batch Submit Approval for an exact finite Attempt set
    -> ExecutionSnapshot
    -> Exact Operational Confirmation
    -> Core WINNER
    -> effect
```

Scientific Approval binds the exact current `CalculationPlan`, its revision,
the semantic meaning shown to the reviewer, and an explicit human decision. It
does not bind resources, profiles, workspaces, PBS bytes, or an
`ExecutionSnapshot`. A changed plan or revision requires a new semantic review
under OD-02. A hash may identify an artifact, but cannot substitute for the
expanded plan semantics or make an old approval current.

Batch Submit Approval binds an explicit finite set of already-existing
`Attempt` records and, for each member, the exact currently approved
`CalculationPlan`, with an explicit human decision over that closed set. A
Batch identifier never acts as a wildcard: future, replacement,
recovery-child, or otherwise unlisted Attempts are not covered. The approval
is not a transaction and grants no automatic replacement, submission, retry,
or scope expansion.

Exact Operational Confirmation binds one exact `ExecutionSnapshot`, including
its prepared bytes, resolved resources and profile/target, workspace, PBS
template, and submission intent. Any snapshot change makes the prior
confirmation stale. Resource, profile, or workspace changes are operational
changes rather than automatic scientific changes, but they require a newly
resolved snapshot and a new exact confirmation.

Each approval or confirmation is non-effectful by itself. Only the complete
current chain passed to the single Execution effect entrypoint may reach the
Core claim. The Controller does not pre-claim. `execute_once(...)` owns
`record_submission_intent(...)`; only its explicit `WINNER` branch may cross
the first effect boundary, while `REPLAY` makes zero effect calls. `UNKNOWN`
creates no retry authority. A child Attempt may reuse scientific approval only
when it still binds the exact same CalculationPlan; it always requires new
Batch Submit Approval membership, a new snapshot, and a new exact operational
confirmation.

## OD-11: Minimal workflow is deterministic orchestration, not effect authority

The v3.0 Workflow layer is an immutable, finite DAG over exact existing Core
identities. Its public package is `auto_g16.workflow`, with focused tests under
`tests/v3/workflow/`. It owns dependency order, bounded static mapping,
condition branches, human orchestration gates, and a deterministic read-only
run projection. It does not redefine Core records or persistence semantics.

Every node binds one exact Core `Task` and one exact `CalculationPlan` ID and
positive revision. The workflow definition enumerates those identities
explicitly; it never discovers the current plan or lists Tasks through a new
Core API. Every possible edge and mapped target is present in the finite
definition. Every Map item contributes its source-to-target dependency to the
same graph as every possible Edge; that combined graph is acyclic and owns the
deterministic topological order and readiness projection. Conditions use a
closed, data-only predicate over an exact supplied Attempt state. Conditional
Edge metadata and each Condition's true/false Edge tuples must agree exactly;
the observed terminal state uniquely derives the complete selected tuple, not
a caller-chosen subset. Arbitrary Python callbacks, shell commands, code
evaluation, dynamic node creation, and open-ended fan-out are not Workflow
features.

The existing Core `WorkflowRun`, `Task`, `Attempt`, and `CalculationPlan`
records remain authoritative for runtime identity and state. A Workflow
evaluation receives an explicit finite node-to-Attempt mapping and validates
every supplied record through public Core APIs. Missing bindings remain
explicitly pending. HumanGate target sets are disjoint; a gate filters only an
already active Node and never activates an inactive branch. A ready node is
only a proposal for the next separately gated action. Workflow never creates a
root or recovery Attempt, claims Core `WINNER`, calls Execution, or crosses an
effect boundary.

`Node.node_id`, `Edge.edge_id`, `Map.map_id`, `Condition.condition_id`, and
`HumanGate.human_gate_id` are non-empty local canonical identifiers scoped to
one exact `WorkflowDefinition`. Each is immutable inside that definition and
unique within its component namespace; all intra-definition references use
these local identifiers. They are not complete-payload UUIDv5 identities and,
alone, grant no cross-definition identity, persistence equivalence, authority,
or effect. Edge-to-Condition and Condition-to-Edge references are ordinary
intra-definition references; component identity computation is never circular.

`WorkflowDefinition.workflow_definition_id` is a schema-versioned,
domain-separated UUIDv5 over the complete canonical definition payload,
including every local identifier and every component's complete semantics.
Reusing a local identifier with changed component semantics therefore changes
the definition identity. Completed `ConditionDecision` and
`HumanGateDecision` records have separate domain-separated deterministic
UUIDv5 identities that bind the exact WorkflowDefinition identity, frozen
Core/run identities, referenced local component identifier, and complete
decision payload. These canonical records use a small Workflow-owned
append-only persistence surface. Exact replay is idempotent; the same authority
identity with different content conflicts. A `WorkflowRunView` is a derived
projection, not separately mutable state. Reopening the same exact definition,
decisions, explicit Attempt bindings, and Core state produces the same view.

A Workflow `HumanGate` is orchestration state only. It never substitutes for
Scientific Approval, Batch Submit Approval, Exact Operational Confirmation,
scientific acceptance, or Core `WINNER`. `UNKNOWN` blocks the affected path and
creates no retry, replacement, child, approval, or effect authority. Recovery
children remain governed by the existing Core and Approval contracts and are
outside automatic Workflow behavior.

## OD-12: Attributed Gaussian facts belong to Result

Scientific validation must consume Result-owned, source-attributed facts; it
must not become a second raw Gaussian parser. The existing
`GaussianLogParser` contract (`auto-g16-v3-gaussian-log`, `1.0.0`,
`gaussian-log-facts`) remains unchanged historical evidence, but its whole-log
aggregate recognition is not sufficient scientific evidence because echoed
user text can contain marker-like strings.

The additive `GaussianJobParser` contract
(`auto-g16-v3-gaussian-job`, `1.0.0`, `gaussian-job-facts`) owns deterministic
exact-byte context recognition, source attribution, generic geometry blocks,
and other scientific-neutral machine-output facts for exactly one structurally
proven Gaussian job. It reuses the existing `ParseOutcome` schema version 1,
Result identity tuple, and append-only provenance chain. Old and new outcomes
coexist without migration, reinterpretation, backfill, or overwrite.

Parser grammar is source-controlled, versioned, deterministic, and pure. Raw
substring occurrence is never authority: route, title, comment, molecular
specification, and other input-echo regions cannot create machine-output facts.
The grammar's literal byte anchors, closed ASCII regexes, LF/CRLF tokenizer,
finite-state transitions, diagnostic codes, and original-byte half-open spans
are normative; an implementation cannot substitute text normalization or a
heuristic context choice.
For this parser tuple, diagnostics are also single-owner authority. Parsing is
strictly left-to-right and fail-fast: `parsed` persists no diagnostic, while
every terminal non-parsed outcome persists exactly one primary closed code.
After a parent production has admitted a child production, that child owns its
first failure; a parent block may not replace or accompany a more specific row
or numeric failure. Exact valid anchors in an illegal state are orphans, while
malformed lookalike prefixes are not. No diagnostic set, ranking pass, or later
failure participates in Result identity.
For a thermochemistry candidate, the current line must pass its exact
structural production, canonical-key resolution, numeric grammar, and finite
conversion before duplicate cardinality is evaluated against previously
committed same-key evidence in that one supported job. A structural or numeric
failure therefore owns the current line before duplicate checking; a fully
valid second same-key occurrence instead owns
`unparseable-duplicate-evidence` over the full current raw-byte line, whether
its value equals or differs from the first occurrence.
Structurally valid multiple jobs are unsupported; malformed, truncated, or
ambiguous context fails closed. Result records attribution and generic facts
only. It never decides whether a geometry is a minimum or grants scientific
acceptance, execution authority, retry authority, or a live effect.

## OD-13: Minimum validation consumes attributed Result facts only

The v3.0 minimum validator belongs to the separate public
`auto_g16.scientific_validation` layer. Its dependency direction is
`ScientificValidation -> Result -> Core`; Core, Result, Approval, Execution,
and Workflow never import it. ScientificValidation is post-Result scientific
classification. It is not another Gaussian parser, execution-status owner,
approval mechanism, retry authority, or human acceptance decision.

The only supported Result tuple is `auto-g16-v3-gaussian-job` / `1.0.0` /
`gaussian-job-facts`. ScientificValidation never opens a Gaussian file, reads
raw output bytes, runs a Gaussian regex, reconstructs a missing fact, or merges
evidence across Results, captures, envelopes, or Attempts. Historical
`gaussian-log-facts` is readable Result history but is `UNSUPPORTED` for this
scientific decision.

One immutable outcome binds the exact CalculationPlan revision, Attempt,
InputBinding, complete OutputEnvelope, ParseOutcome Result, and
source-controlled validation policy/version. The four and only machine
classifications are `VALIDATED_MINIMUM`, `NOT_MINIMUM`, `INCOMPLETE`, and
`UNSUPPORTED`. The accepted optimization/stationary pair, final optimized
geometry, and post-stationary frequency evidence are selected deterministically
from Result-owned source spans; no favorable subset or nearest-looking fact is
permitted. Each outcome carries exactly one source-controlled primary reason
code selected by the frozen validation order; an implementation cannot collect,
rank, or reorder multiple reasons.

V3.0 supports only ordinary nonlinear minima with at least three non-dummy
atoms and exactly `3*N - 6` attributed post-stationary frequencies. Fewer
modes are `INCOMPLETE`; more modes, fewer than three atoms, or atomic number
zero are `UNSUPPORTED`. Every finite frequency below zero is imaginary, with
no tolerance: one or more negatives is `NOT_MINIMUM`, while exactly zero
negatives on otherwise complete supported evidence is `VALIDATED_MINIMUM`.
Error termination is `INCOMPLETE`.

Human `ScientificAcceptance` is a separate immutable record and may bind only
one exact `VALIDATED_MINIMUM` outcome. It never mutates Result, Attempt,
CalculationPlan, or the validation outcome. Outcomes and acceptances use a
small ScientificValidation-owned append-only persistence boundary, separate
from Core and Result schemas. Exact replay is idempotent; conflicting content
under one identity fails closed.

## OD-14: Minimum-validation public shape is closed before implementation

The public `auto_g16.scientific_validation` inventory remains exactly the
eleven names frozen by OD-13 and the v3 boundary specification. No public
policy, span, geometry, evidence, protocol, or service class is added.

Schema version `1`, validation policy ID
`auto-g16-v3-minimum-validation`, and policy version `1.0.0` are fixed
source-controlled values and are never caller-selectable. The namespace root
is `f4617d31-5b90-5c79-888a-9b9ccec5e612`; the only identity domains are
`minimum-validation-outcome` and `scientific-acceptance`, with each domain
namespace derived by UUIDv5 from
`auto_g16.scientific_validation/v1/<domain>`.

`MinimumValidationOutcome` and `ScientificAcceptance` are frozen immutable,
slotted, keyword-only, service-created records. Their exact public fields and
the exact signatures of `validate_minimum`, `record_minimum_validation`,
`record_scientific_acceptance`, and `require_scientific_acceptance` are owned
by `docs/v3/boundary-spec.md`. Outcome identity binds every authority field,
including the complete selected Result mappings and frequency values.
Acceptance identity binds one exact persisted validated outcome plus reviewer
identity and canonical review evidence. Multiple explicit acceptances may
coexist; no latest/current selection exists.

Identity uses the frozen tagged canonical-value encoding: distinct tags for
null, boolean, integer, finite float, string, mapping, and sequence; lexical
mapping-key order; sequence order preservation; and compact UTF-8 canonical
JSON. Unsupported values, non-finite floats, container cycles, malformed
replay, and same-ID/different-payload replay fail closed. ScientificValidation
extracts this algorithm locally and must not import Workflow or any private
Core encoding.

This decision changes no scientific policy and introduces no raw Gaussian
interpretation. ScientificValidation continues to depend only on public Result
and Core records, owns its separate append-only store, and makes no Core,
Result, Approval, Execution, or Workflow API/schema change.

## OD-15: Minimal Observe is read-only exact-Attempt evidence projection

The v3.0 Observe layer belongs to the public `auto_g16.observe` package, with
focused tests under `tests/v3/observe/`. It records what was observed about one
exact existing Core `Attempt`; it does not decide what the controller should do
next. Core continues to own Attempt state and append-only Observation history,
Execution owns effects, Workflow owns orchestration, Result owns attributed
program facts, and ScientificValidation owns scientific classification.

Observe reuses the existing public Core `Observation`, `SQLiteRuntimeStore`,
`append_observation`, and `observations_for_attempt` boundary without a Core
schema or API change. One Observe record is one immutable source-axis sample:
`scheduler`, `process`, or `gaussian`. It binds the exact Attempt, exact source
evidence identity, canonical UTC observation time, source-owned freshness,
closed source-specific state, and optional nonnegative Gaussian progress
position. Its deterministic UUIDv5 identity binds that complete payload.

The current projection is derived only from the complete persisted matching
Observation history in Core append order. The last appended valid sample for
each source axis is exposed. Freshness and observed state are independent:
known state remains known when its evidence is stale, while explicit
`unknown` remains unknown whether its evidence is fresh or stale. An older
optimistic value is never carried forward over a newer explicit unknown sample,
but staleness alone never converts a known state to unknown. Observation time
is displayed evidence, not a caller-selectable ordering override. Reopening the
same history produces the same projection. Exact replay is idempotent, while
malformed matching evidence or same-ID/different-payload history fails closed.

Scheduler terminal or absent evidence is not Gaussian completion; process
absence is not failure; a Gaussian phase or coarse progress position is not a
Result or scientific conclusion. Queued, held, running, exiting, unchanged,
slow, stale-known, absent, and explicit unknown evidence never creates failure,
retry, replacement, recovery-child, submission, cancellation, cleanup,
execution, or scientific-acceptance authority. Observe performs no transport,
scheduler, filesystem, Gaussian, or Core-state effect.

Legacy direct/qstat and RTwin monitoring code remains a reuse/history source.
Its strict present/absent/unknown distinctions and neutral scheduler/process
state vocabulary may be extracted, but its owner, receipt, capability,
transport, profile-hash, and lineage governance is not v3 Observe authority.
Existing Gaussian parsers remain Result authority and are not ported into
Observe. Any future live acquisition or incremental Gaussian phase recognizer
requires its own later contract and effect/read boundary.

## OD-16: ReviewBundle is a deterministic projection, not authority

The minimum v3.0 human-review surface belongs to the public
`auto_g16.review` package, with focused tests under `tests/v3/review/`. It is a
pure, immutable projection over exact persisted Core, Result, and
ScientificValidation authority. It creates no scientific fact, chooses no
current or favorable evidence, grants no acceptance or execution authority,
and performs no persistence or external effect.

One `ReviewBundle` closes the exact CalculationPlan and Attempt, InputBinding,
ExecutionSnapshot identity, OutputEnvelope, ParseOutcome, selected geometry
and complete selected frequency evidence, MinimumValidationOutcome and its one
primary reason, plus an explicitly supplied finite set of
ScientificAcceptance identities. The builder replays these public records and
rejects cross-plan, cross-Attempt, cross-envelope, cross-Result, or
cross-outcome splicing. Acceptance state is only a deterministic projection of
the exact outcome and the explicit acceptance set; there is no latest/current
selection and no acceptance operation in the Review layer.

The bundle has a domain-separated deterministic UUIDv5 identity over its
complete canonical projection payload. The only minimum renderer is
deterministic JSON of that exact typed bundle. Rendering adds no timestamp,
filesystem path, viewer state, prose interpretation, or hidden evidence.
GaussView and other external viewers may later wrap an explicitly exported
geometry projection under their own separate authority, but are not imported,
invoked, or treated as ReviewBundle authority.

The InputBinding, OutputEnvelope, and ParseOutcome projections explicitly
include their existing derived public authority references
(`observation_id`, `observation_id`, and `result_id`, respectively). The
builder obtains and verifies those IDs from the exact typed public records; it
accepts no caller-supplied replacement. Each projection has one closed key set,
and the same complete mapping binds both ReviewBundle identity and
deterministic rendering. These references make the exact reviewed authority
chain visible without making Review a second identity or authority owner.

Review depends only on public Core, Result, and ScientificValidation surfaces.
No upstream package imports Review. The ScientificValidation public shape may
be referenced during contract freeze, but Review implementation remains
blocked until ScientificValidation implementation is integrated; no local stub
or substitute record may fill that dependency.

## OD-17: V30-A composition is RTwin-first and has one Execution effect owner

The V30-A Controller is a composition role, not a new public package or effect
owner. It must replay `validate_effect_authority(...)`, validate every exact
non-effect input, and then call the existing public Execution
`execute_once(...)` entrypoint. It must not call
`record_submission_intent(...)` itself. `execute_once(...)` alone owns that
Core claim and sequences it after all non-effect validation. Only `WINNER`
crosses the first workspace or remote effect boundary; `REPLAY` makes zero
adapter, filesystem, transport, scheduler, or Gaussian calls.

Official composition never calls `execute_once(...)` after Approval replay has
observed a non-`PLANNED` Attempt. A valid concurrency test lets two Controllers
finish pure authority replay against the same still-`PLANNED` Attempt before a
barrier; their concurrent `execute_once(...)` calls yield one `WINNER` and one
`REPLAY`, with the replaying port receiving zero calls. Any later invocation
must first replay current Approval, fail there because the Attempt is no longer
`PLANNED`, and make zero Execution or adapter calls. Bypassing that pure gate to
obtain a sequential `REPLAY` is invalid Controller composition.

This is an at-most-once effect seam, not a distributed atomic transaction.
Once `WINNER` has been recorded, a crash, lost connection, malformed reply, or
otherwise ambiguous remote outcome cannot roll the claim back and cannot
authorize automatic retry. Durable `possibly_effectful` evidence and
same-Attempt read-only reconciliation remain the only legal uncertain path.

V30-A uses one RTwin/PBS adapter behind the already integrated public
`ExecutionPort`. A separate read-only transport port acquires scheduler and
fetch evidence. Process acquisition is deferred. The Controller maps acquired
scheduler state into public Observe records; transport never records Observe
authority.
The Controller maps fetched bytes and exact capture metadata into public
Result `OutputEnvelope`/`OutputArtifact` records and invokes the public Result
parser; transport never creates a `ParseOutcome` or program fact. Direct
`OpenSSHTransport`, qdel/cancellation, cleanup, deployment, and all live
operations remain deferred to separate Owner gates.

RTwin operations use one source-controlled, versioned, digest-attested private
operation table. Executables and endpoint/runtime bindings come only from the
exact resolved snapshot/profile; argv, operation token, cwd, environment,
timeouts, output caps, and `shell=False` are fixed by the Transport contract.
No caller command, shell text, retry, secret, or mutable environment is part of
the operation surface. Fetch returns bounded immutable bytes and metadata
only; it writes no local output target.

Read authority begins only from a public `ReceiptJournal` lookup by exact
persisted receipt ID for the exact Attempt; a caller-created or unpersisted
`RemoteEffectReceipt` grants nothing. Exactly one durable confirmed submission
or reconciliation receipt must close against the current snapshot. Every read
also receives the current public non-secret `ServerProfile`, resolves it through
the public Execution resolver, and requires complete semantic/identity/effective
digest equality with the snapshot before any driver call. Secrets remain
out-of-band mechanics, never snapshot, receipt, binding, or evidence authority.

The new public surface is confined to `auto_g16.transport`, with tests under
`tests/v3/transport/`. Existing Core, Approval, Workflow, Execution, Observe,
Result, ScientificValidation, and Review public APIs and schemas remain
unchanged. A complete synthetic composition test must prove the exact chain
through `WINNER`, Observe, fetch, Result, ScientificValidation, ReviewBundle,
and separate ScientificAcceptance while making no network, PBS, Gaussian, or
other live call.

## OD-18: Transport persists physical authority and starts from an explicit trust anchor

Transport owns one independent append-only SQLite `TransportStore`. It is
separate from Core and Execution persistence and is shared by the RTwin effect
and read adapters. It durably binds the exact Attempt, ExecutionSnapshot,
submission intent, logical remote Attempt workspace, opaque remote physical
workspace token, staged artifact identities and physical tokens, and the later
exact job/receipt association. Exact replay is idempotent; a conflicting
identity or a second physical object for one logical binding fails closed.
The store grants no Core transition, submission, retry, read, or scientific
authority by itself.

The store provides clone/replacement detection, not uncloneability. Creation
uses one non-caller-selectable 32-byte OS-CSPRNG nonce and binds exact
`transport_store_id` plus `store_instance_id` to the approved lexical root/
path, physical database file identity, and ordered parent identity chain. Those
IDs close every TransportStore record and public remote-job binding. The threat
model excludes a malicious same-UID process, root/administrator, kernel or
filesystem compromise, and compromised deployment/bootstrap authority; no
ordinary SQLite/path contract can honestly defeat those actors.

The trusted remote agent allocates a fresh workspace and returns its opaque
physical token only after descriptor-relative, no-follow verification. Every
later stage, qsub, qstat, reconciliation, and fetch supplies that persisted
token; the agent reopens from its approved root and reattests every component
descriptor-relatively before the operation. Each staged artifact similarly
receives a post-write token which is reattested before qsub or fetch. A path
check followed by an ordinary pathname mutation, an in-memory-only allocation
set, or a token that disappears at process restart is not sufficient.

The preinstalled `server_python` manifest root and remote OS/deployment boundary
provide its pre-start trust. It neither authenticates itself nor proves its own
pre-launch integrity. It accepts only the fixed protocol-owned bootstrap source
and closed data-only operation vocabulary and may attest downstream protocol/
runtime data after startup. Dynamic/caller source or agent upload, `eval`,
`exec`, arbitrary module loading, or caller-selected operation is forbidden.
This decision authorizes no deployment, credential authority, host-key change,
or live operation.

Executable trust comes from the exact approved deployment manifest: absolute
path, platform, attestation mode, deployment identity, required digest/size,
and the exact remote-shell grammar/null matrix. Runtime attestation then checks
physical identity, regular/executable type, no-follow path, and deployment-owned
permission conditions where its mode requires them. No PATH lookup, symlink,
reparse point, or caller executable is accepted. Exact
OS/deployment-trusted absolute-path execution is permitted; descriptor
execution and a new native wrapper are not required. Transport performs strict
prelaunch and practical postlaunch reattestation but does not claim to close
TOCTOU against an excluded same-UID actor. Local/RTwin first-hop argv and any
unavoidable POSIX command string use their exact frozen parser/quoting rules;
caller shell text is never accepted. Every channel remains bounded and requires
completion plus EOF. These rules do not change the WINNER seam, unchanged
`ExecutionPort`/receipt APIs, RTwin-first selection, OpenSSH deferral, or the
prohibitions on retry, qdel, deletion, cleanup, deployment, and live work.

## OD-19: Deployment manifest closes the fixed bootstrap and remote-shell chain

The canonical runtime content named exactly
`transport-deployment-manifest-v1.json` is the final pre-start Transport trust
authority inside the v3.0 threat model. Transport obtains those bytes only from
the current `ServerProfile`, resolves that profile through the existing public
Execution boundary, requires exact equality with the current
`ExecutionSnapshot.resolved_server_profile`, and requires the manifest byte
identity to equal the same fixed entry in `runtime_identities`. There is no
second manifest input, alias, fallback, latest lookup, or global manifest. A
byte change therefore requires a new resolved profile, snapshot, and exact
operational confirmation without any Execution API/schema change.

The manifest has one exact canonical JSON schema and exactly nine trust roots:
Mac SSH/SCP, RTwin SSH/SCP, the configured RTwin remote shell, the configured
server POSIX shell, server Python, qsub, and qstat. The remote shells are
deployment roots because they necessarily interpret the first remote command;
local `shell=False` removes only an additional local shell. The manifest chooses
exactly `powershell-v1` or `cmd-v1` for RTwin and `posix-sh-v1` for the server;
there is no detection or fallback. Under this nine-root model,
`powershell-v1` owns the frozen hash/size/file launcher. `cmd-v1` has a frozen
quoting grammar but is operationally incompatible and fails closed because the
shell has no trusted SHA-256 primitive and adding one would create a tenth root.

The exact trusted server Python may run one fixed source-controlled loader
owned by bootstrap protocol `auto-g16-v3-rtwin-bootstrap/1`. That fixed source
is not caller code: it reads one canonical length-bounded data packet and
dispatches only the frozen operation enum. No arbitrary `RUN`, `EXEC`, `SHELL`,
`PYTHON`, `SCRIPT`, module, callback, source, executable, or command is accepted.
Each of the seven operations has one exact request binding/payload schema and
one exact response result schema, including closed conditional cardinality for
stat and reconciliation. The only authority-bearing response path is one
bounded AGV3 frame on the nested process's stdout; bootstrap stderr is capped
diagnostic-only and must be empty for an accepted response. Stage and fetch
carry exact bytes as bounded canonical base64 in those frames. There is no
unspecified binary side channel, stdout truncation, caller-selected status, or
implementation-defined physical/job/result object.
After deployment-trusted startup, server Python may detect drift in itself and
attest the exact qsub/qstat paths before structured-argv execution, but none of
those checks creates or proves its pre-start trust. Manifest authority answers
which deployment components are trusted; `TransportStore` separately records
which physical workspace/artifact/job objects were used and never becomes
deployment authority.

The fixed trust chain is Deployment/OS -> manifest -> configured remote shells
and executables -> fixed bootstrap -> closed data protocol -> Transport
mechanical evidence. It does not claim to defeat malicious root, a compromised
OS/kernel or deployment authority, or a fully compromised same-UID controller.
This decision preserves the WINNER seam, RTwin-first selection, OpenSSH
deferral, no retry/qdel/delete/cleanup, and the no-live boundary.

## OD-20: Fixed bootstrap source is code authority, not a variable shell token

The exact source-controlled loader owned by
`auto-g16-v3-rtwin-bootstrap/1` is one fixed protocol constant, distinct from
manifest-, profile-, operation-, and caller-controlled tokens. Variable tokens
continue to reject NUL, CR, and LF and may enter the remote operation only as
closed AGV3 stdin data. They are never interpolated into shell/Python source,
an executable/module name, or the `-c` argument.

The fixed bootstrap source may contain ASCII LF so it remains readable and
auditable Python. It rejects CR and NUL, uses LF-only line endings, has one
frozen source size/SHA-256 identity, and changes only through a reviewed
bootstrap protocol/source update. The launcher remains exact manifest
`server_python`, fixed `-I -S -B -c`, then that one exact source word. A
deterministic POSIX single-quote encoder preserves the source bytes—including
LF and literal single quotes—as one shell word; no variable value is ever
concatenated into it. This narrow exception does not make LF legal in any
manifest field, path, identity, filename, operation, option, argv value, or
AGV3 metadata string.

The mutable operation boundary remains the sole bounded canonical AGV3 frame
on stdin. The source contains only the closed parser, validation, and dispatch
implementation; it cannot evaluate request source, load a caller-selected
module, or expose generic `RUN`, `EXEC`, `SHELL`, `PYTHON`, or `SCRIPT`.
This clarification changes no trust root, manifest, TransportStore, WINNER,
ExecutionPort, upstream public API/schema, retry, OpenSSH, deployment, or live
authority.

The reviewed source-identity successor may change the fixed source bytes while
retaining bootstrap protocol `auto-g16-v3-rtwin-bootstrap/1` only when the AGV3
frame, all seven closed request/response schemas, operation table, and trust
semantics remain byte-for-byte or semantically unchanged. The source successor
with size `13904`, exactly 190 LF, zero CR/NUL, and SHA-256
`056e27cab0a00e305c5e5acc7f5673e7d196dd0dc27516c31ec2cb95d6b58952`
implements already-frozen cap and postlaunch-attestation requirements; it adds
no operation, authority, channel, or caller-controlled code. Therefore this is
an explicit reviewed source-identity update, not a protocol-version change.

## OD-21: Scheduler resources are snapshot authority enacted by a closed dialect renderer

`ExecutionSnapshot.resolved_resource_request` is the only semantic authority
for scheduler cores, memory in integer MB, walltime in integer seconds, and an
optional explicit queue. A PBS template, caller qsub argument, environment,
ServerProfile resource default, Gaussian `%nprocshared`/`%mem`, scheduler
default, or legacy resource-governance record cannot override, fill, or replace
those values. `PbsTemplateBinding` continues to reject caller-controlled
`#PBS -l`, `#PBS -q`, and equivalent resource directives.

Transport derives one private mechanical resource-enactment value from the
identity-closed snapshot. It repeats the exact snapshot and resolved-resource
request IDs and exact four resource values, then adds only the scheduler
dialect ID selected by current-profile runtime content named exactly
`pbs-resource-enactment-v1.json`. That canonical JSON content has the closed
two-key schema `auto-g16-v3-pbs-resource-enactment/1` plus one closed dialect
identifier. It contains no executable, argv, option, template, format string,
shell text, resource value, credential, or scientific authority. Its bytes are
already included in `ResolvedServerProfile.runtime_identities`; changing the
dialect therefore requires a new resolved profile, ExecutionSnapshot, and
exact Operational Confirmation without changing the public Execution API.

`SUBMIT_QSUB_ONCE` carries the closed resource-enactment value as data. The
Transport adapter first identity-checks the current snapshot/profile and proves
the derived value equals that snapshot exactly before constructing the request.
The fixed server bootstrap validates the request's exact closed schema and
internal field types, selects one source-controlled renderer solely by the
dialect ID, and deterministically renders the final structured argv from that
ID, the exact resource data, and the exact PBS basename. The bootstrap does not
claim independent access to or reconstruction of the ExecutionSnapshot. It then invokes the
manifest-bound qsub executable with `shell=False`. There is no caller argv,
shell/eval/template evaluation, PATH lookup, queue fallback, float conversion,
walltime rounding down, or implicit scheduler-default satisfaction.

An explicit queue must render exactly or submission fails closed; null queue
emits no queue selector. Walltime conversion uses exact integer arithmetic and
fails if the selected dialect cannot represent the exact seconds. Memory is
rendered from exact integer `memory_mb`, never Gaussian `%mem`; cores are
rendered from exact integer `cores`, never `%nprocshared`. A derived argv is
mechanical review evidence only and cannot become a second mutable authority.
Any snapshot/resource/dialect/payload mismatch rejects before qsub.

Because the closed request schema and operation-table semantics change, this
successor uses bootstrap protocol `auto-g16-v3-rtwin-bootstrap/2`, operation
table `auto-g16-rtwin-operation-table/2`, and a new exact fixed bootstrap
source identity. It retains the same seven operations, one AGV3 frame in each
direction, trust-root inventory, bounded channels, and no-shell/no-retry trust
semantics. Protocol `/1` remains immutable historical evidence and is not
silently reinterpreted.

No production dialect is inferred from generic PBS, Torque, PBS Pro, or
OpenPBS knowledge. Historical repository/live artifacts prove that the legacy
deployment accepted PBS-script resources in `nodes=1:ppn`, integer-GB memory,
and `HH:MM:SS` walltime form, but did not by themselves prove a current
structured-qsub queue or resource-option dialect. They remain reuse evidence.
OD-22 separately records the exact accepted read-only deployment evidence and
the one qualified production renderer. Offline synthetic evidence continues to
use one closed, clearly non-production renderer that is rejected by the live
subprocess driver; it cannot satisfy or impersonate production qualification.

This decision changes no public Core, Approval, Workflow, Execution, Observe,
Result, ScientificValidation, or Review API/schema. It creates no resource
planner, adaptive allocation, automatic queue choice, retry, qdel, cleanup,
deployment, credential, host-key, OpenSSH, or live authority. `WINNER` remains
the sole first-effect sequencing gate; `REPLAY` performs zero qsub and
`UNKNOWN` never authorizes a second qsub.

## OD-22: The first production scheduler dialect is exact Torque 6.1.0 single-node ppn

The accepted read-only deployment preflight closes the previously unresolved
production dialect for the exact V30-A target. The observed `qsub` and `qstat`
are `/usr/local/bin/qsub` and `/usr/local/bin/qstat`; they report Torque
`6.1.0`, `qsub` links `libtorque.so.2`, the server is active, the target is one
44-processor node, and the qualified queue is exactly `batch`. The exact
preflight identities are: qsub size `418920`, SHA-256
`f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d`;
qstat size `185656`, SHA-256
`3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a`.
Neither binary is package-manager-owned, so package identity is not invented.
The deployment manifest continues to own executable path, size, digest, and
permission attestation; the renderer never returns an executable.

The one production dialect ID is exactly
`auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1`. It consumes only
the identity-closed `ResolvedResourceRequest` plus exact portable PBS basename
and renders exactly `("-l",
"nodes=1:ppn=C,mem=Mmb,walltime=W", "-q", "Q", "B")`, where `C`, `M`, and
`W` are unsigned canonical decimal encodings of positive non-boolean integer
cores, memory MB, and walltime seconds. No GB conversion, time reformatting,
split resource clauses, option reordering, caller fragment, PBS directive,
environment, scheduler default, or legacy tier participates.

For the first V30-A deployment the queue is mandatory and must equal exactly
`batch`. `queue = null` and every other queue fail closed. Although the
observed scheduler default is `batch`, that default is deployment evidence,
not resource authority. An explicit queue therefore always renders as the
exact pair `-q`, `batch`. Supporting another queue or another deployment is a
separate deployment-qualified gate.

The runtime descriptor remains the two-key canonical
`pbs-resource-enactment-v1.json`; it admits exactly the unchanged synthetic
test dialect and this Torque production dialect. The synthetic renderer stays
non-production and rejects before process creation. The Torque renderer is
production-qualified and may be marked mechanically `live_capable = true`,
but that flag grants no live authority: the complete Approval, snapshot,
Operational Confirmation, Core WINNER, deployment-manifest, and explicit
V30-A Live Owner Gate remain mandatory.

This decision closes only dialect qualification. It changes no public Core,
Approval, Workflow, Execution, Observe, Result, ScientificValidation, or
Review API/schema and creates no planner, multi-node policy, automatic queue
choice, retry, qdel, cleanup, deployment, credential, host-key, OpenSSH, or
live authority. PBS templates remain free of active `#PBS -l` and `#PBS -q`
resource directives; `REPLAY` performs zero qsub and `UNKNOWN` never permits a
second qsub.

## OD-23: Both RTwin SSH hops enact one closed profile-bound configuration

For the first V30-A live path, recording SSH configuration in a resolved
`ServerProfile` is insufficient unless the exact same configuration is used at
the process boundary. Transport therefore consumes the existing public
`ServerProfile.platform_paths`, `config_files`, `host_key_policy`,
`batch_mode`, and `identities_only` fields; it adds no Execution field, schema,
credential record, or executable trust root.

The Transport convention is closed. `platform_paths` provides exactly the
four effect-configuration keys `mac_ssh_config_path`,
`mac_known_hosts_path`, `rtwin_ssh_config_path`, and
`rtwin_known_hosts_path` in addition to unrelated existing path authority.
For a Transport operation, `config_files` contains exactly one immutable byte
value for each logical name
`mac-ssh-config`, `mac-known-hosts`, `rtwin-ssh-config`, and
`rtwin-known-hosts`, and contains no other logical name; duplicate, missing,
or extra names reject. This exact-set rule is Transport-private and does not
change what the generic public Execution resolver can resolve. These files are
profile-bound effect configuration, not additions to
the nine-root deployment executable inventory. Private-key bytes, private-key
digests, agents, tokens, and passwords remain outside profile, manifest,
runtime content, TransportStore, logs, and review packets.

Each SSH config is UTF-8 without BOM, NUL, CR, or HTAB, ends in exactly one LF,
has exactly one concrete single-name `Host` stanza, and may contain only
`Host`, `HostName`, `User`,
optional `Port`, `IdentityFile`, `IdentitiesOnly`,
`StrictHostKeyChecking`, and `UserKnownHostsFile`. The required values include
one dedicated absolute identity path, `IdentitiesOnly yes`,
`StrictHostKeyChecking yes`, and the matching bound known-hosts path. An absent
`Port` means exactly 22 and is legal only when the resolved profile also says
22. Wildcards, multiple aliases or stanzas, quoting/escaping, continuation,
unknown directives, and in particular `Include`, `Match`, `exec`,
`ProxyCommand`, `ProxyJump`, command hooks, every forwarding directive,
`KnownHostsCommand`, providers, and `IdentityAgent` reject before a process.
The first-live topology is exactly one Mac-to-RTwin hop and one
RTwin-to-server hop; an additional proxy hop requires a later separately
closed profile convention.

The parsed Mac Host alias resolves exactly to the sole `jump_topology` host,
port, and user. The parsed RTwin Host alias resolves exactly to the final
target host, port, and remote user. Commands target those aliases and
explicitly pass the bound `-F` file, `BatchMode=yes`, `IdentitiesOnly=yes`,
`StrictHostKeyChecking=yes`, public-key-only authentication, and no identity
agent. Both `UserKnownHostsFile` and `GlobalKnownHostsFile` are set to the same
exact bound known-hosts path, so no ambient user or global file can authorize
a different key. There is no `~/.ssh/config`, default-known-hosts, agent,
password, keyboard-interactive, caller-option, caller-config, or caller-target
fallback. `boundary-spec.md` freezes exact SP-only parsing and the complete
ordered argv templates; Transport may not reorder or combine those tokens.

Before launch, Transport resolves the current profile through the existing
public Execution resolver and requires complete equality with the snapshot.
It then proves exact profile bytes against the four named files. The Mac
controller opens its two local files no-follow as regular files and compares
size, SHA-256, and descriptor/name identity before process creation and again
after process completion. A prelaunch mismatch causes zero process. A
postlaunch drift rejects the child result; if an effect may have crossed,
normal `UNKNOWN`/reconciliation authority applies and never authorizes retry.
The manifest-bound PowerShell launcher performs the same regular/non-reparse
size/SHA-256 attestation for the two RTwin files before nested SSH and, where
the nested process completes, after it. A prelaunch mismatch causes zero
nested SSH. Postlaunch drift makes the result unusable and preserves `UNKNOWN`
when applicable. No case retries. Runtime/review evidence exposes only logical identity, path class,
size, digest, and PASS/FAIL; machine-specific contents and addresses are not
committed.

This is an effect-seam repair, not a new transport mechanism or authority.
The existing dedicated Mac and RTwin configs and strict host-key topology are
WRAPPED/PORTED as mechanical facts while all legacy owner, receipt,
capability, hash-currentness, retry, and cleanup governance stays excluded.
The pre-repair resolved profile identity is failed evidence and cannot be used
for live authority. After integration, the live packet creates a new
ServerProfile revision and new resolved identity before any Attempt exists.
No `execute_once`, Core claim, workspace mutation, qsub, Gaussian, qdel,
cleanup, automatic retry, deployment, or other live effect is authorized.
