# Auto-G16 v3 boundary: observe

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:2351-2563 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-OBS-MIN-CONTRACT-01 Frozen Minimal Observe Contract

**Status: CONTRACT FREEZE CANDIDATE; IMPLEMENTATION NOT AUTHORIZED.** This is a
read-only evidence boundary. It introduces no Core, Execution, Result,
ScientificValidation, Approval, or Workflow API/schema change and authorizes no
transport or live observation.

### Package and exact public inventory

The only public package is `auto_g16.observe`; its focused test package is
`tests/v3/observe/`. The public inventory is exactly:

```text
OBSERVATION_TYPE
AttemptObservation
AttemptObservationProjection
ObserveBoundaryError
record_attempt_observation
project_attempt_observations
```

`OBSERVATION_TYPE` is the source-controlled string
`auto-g16-v3-attempt-observation`. `ObserveBoundaryError` is a `ValueError`.
No public transport, callback, parser, retry, diagnosis, policy, mutable view,
or effect interface is part of this contract.

`AttemptObservation` is frozen, slotted, keyword-only, and immutable. Its exact
fields are:

```text
observation_id: str                         # init=False
attempt_id: str
source_kind: str
source_identity: str
observed_at_utc: str
freshness: str
state: str
progress_position: int | None
```

`attempt_id`, `source_identity`, and `observed_at_utc` are nonempty. The time
uses exact `YYYY-MM-DDTHH:MM:SS.ffffffZ` UTC syntax, must denote a real UTC
instant, and is evidence only; it is not used to reorder persisted history.
`freshness` is exactly `fresh`, `stale`, or `unknown` and remains the source
acquisition owner's classification. Observe does not recompute it from ambient
time. Freshness is independent of `state`: a closed known state does not become
`unknown` merely because its evidence is stale, and explicit state `unknown`
may itself carry `fresh`, `stale`, or `unknown` freshness.

The closed state matrix is:

```text
scheduler -> queued | running | held | exiting | terminal | absent | unknown
process   -> active | absent | unknown
gaussian  -> not-started | startup | scf | optimization | frequency |
             termination | unknown
```

`progress_position` is `None` for scheduler and process samples. For a Gaussian
sample it is `None` or a nonnegative integer denoting an exact coarse source
position supplied by the read-only acquisition owner. It is not a percentage,
convergence claim, liveness proof, completion claim, or scientific fact.

`AttemptObservationProjection` is a frozen, slotted, keyword-only derived view
with exact fields:

```text
attempt_id: str
scheduler: AttemptObservation | None
process: AttemptObservation | None
gaussian: AttemptObservation | None
observation_count: int
```

It has no separately persisted identity and cannot be caller-constructed as
authority.

### Deterministic identity and Core persistence

Observe schema version is `1`. Its source-controlled UUIDv5 namespace root is
`653e9a6f-0d59-503c-ab13-ddd6e5055fe4`; the
`attempt-observation` domain namespace is
`7c81caec-1f1d-5114-81a6-b72a537c4f4e`. The domain namespace is UUIDv5 of the
root and literal `attempt-observation`.

The UUIDv5 name is compact UTF-8 JSON over this exact ordered array:

```text
[
  1,
  attempt_id,
  source_kind,
  source_identity,
  observed_at_utc,
  freshness,
  state,
  progress_position
]
```

JSON uses `ensure_ascii=false`, separators `,` and `:`, and `allow_nan=false`.
Every element is already closed to string, integer, or null; Boolean is not an
integer. Formatting, local path, insertion order, ambient time, and temporary
location never affect identity.

The normative replay vector is:

```text
payload = [1,"attempt-1","scheduler","source-qstat-1",
           "2026-08-22T00:00:00.000000Z","fresh","running",null]
observation_id = cdce89f6-8d2e-51b1-b5b0-7f6c48358e95
```

```text
record_attempt_observation(
    store: SQLiteRuntimeStore,
    observation: AttemptObservation,
) -> None
```

This function verifies the record and appends one public Core `Observation` whose
`observation_id` and `attempt_id` match the Observe record, whose
`observation_type` is exactly `OBSERVATION_TYPE`, and whose canonical `data`
contains exactly `source_kind`, `source_identity`, `observed_at_utc`,
`freshness`, `state`, and `progress_position`. The existing Core store proves
that the Attempt exists, preserves append order and reopen durability, makes
exact same-ID/same-payload replay idempotent, and rejects
same-ID/different-payload conflicts. Observe creates no separate database and
no Core migration.

```text
project_attempt_observations(
    store: SQLiteRuntimeStore,
    *,
    attempt_id: str,
) -> AttemptObservationProjection
```

This function loads the existing Attempt through the public Core store and
scans the complete append-ordered Observation history.
Non-Observe observation types are ignored. Every matching Observe record is
decoded with exact fields and its identity is recomputed before projection;
one malformed, cross-Attempt, or identity-inconsistent matching record fails
the whole projection closed. For each `source_kind`, the last appended valid
record wins. Its `state` and `freshness` are projected independently: a newer
stale `running` or `queued` record remains respectively `running` or `queued`,
while a newer explicit state `unknown` remains unknown whether fresh or stale.
When an axis has no usable persisted Observe record, its projection slot is
`None`, which is the projection's no-evidence UNKNOWN case; it must not be
confused with the known source state `absent`. Malformed matching evidence
still fails the whole projection closed rather than being silently converted to
unknown. `observation_count` counts all validated matching Observe records. The
same persisted history always yields the same projection.

### Authority, replay, and failure boundaries

An Observe record preserves a supplied source evidence identity but does not
self-authenticate the acquisition, transport, file, process, qstat executable,
or Gaussian source. A later acquisition owner must separately validate those
bytes and source semantics before recording a sample. Observe never follows a
path, reads a Gaussian log, invokes qstat/ps, opens SSH, or calls a program.

`scheduler=terminal` or `scheduler=absent` does not imply Gaussian completion;
`process=absent` does not imply failure; `gaussian=termination` does not encode
normal versus error termination and does not create a Result. A repeated or
unchanged `progress_position`, stale sample, slow job, or nonterminal state is
not failure. Stale known evidence preserves its latest durable known state and
marks freshness separately; it is neither `unknown` nor `failed`. Explicit
state `unknown` replaces an older optimistic state for its axis, while absence
of any usable axis evidence remains `None`/UNKNOWN. None of these states or
freshness values changes Core Attempt state or authorizes retry, replacement,
child creation, submission, cancellation, cleanup, execution, parsing,
validation, or acceptance.

### Narrow reuse adjudication and non-goals

**PORT:** the public Core `Observation`, `SQLiteRuntimeStore`, Attempt existence
check, append-order query, idempotent exact replay, conflict rejection, and
durable reopen behavior.

**EXTRACT:** only the neutral scheduler lifecycle vocabulary and strict
present/absent/unknown and process present/absent/unknown distinctions evidenced
by the legacy direct qstat/read-only tests. The legacy stale-to-unknown coupling
is not ported; v3 preserves typed state and freshness as independent evidence
axes.

**WRAP:** exact Core Attempt binding and Core Observation persistence behind
the two small public Observe service functions.

**REWRITE:** the compact typed Observe record and deterministic per-axis
projection. The legacy monitor cannot reasonably be ported because it couples
freshness and acquisition outcomes to remote acquisition, v2
owner/receipt/capability/profile/hash-lineage governance, projection, and live
operational policy instead of preserving independent typed evidence axes.

**DROP:** legacy owner chains, receipts, capabilities, profile/hash-lineage
authority, caller path fallbacks, qsub/qdel/cancellation/retry behavior,
scientific acceptance, and any inference that scheduler terminal means
Gaussian completion.

**DEFER:** live qstat/ps/log acquisition, transport, OpenSSH/RTwin/PBS wiring,
the exact incremental Gaussian phase recognizer/source grammar, full stall or
failure diagnosis, resource telemetry/planning, automatic repair/retry,
ReviewBundle, and every live operation. Existing `GaussianLogParser` and
`GaussianJobParser` remain Result parsers and are not ported into Observe.

Core owns Attempt state/history; Execution owns effects; Observe owns only its
Observation payload and derived projection; Workflow owns orchestration;
Result owns parsed facts; ScientificValidation owns scientific classification.
The dependency direction is `Observe -> Core`; upstream layers never import
Observe. Contract integration alone authorizes neither selector ownership nor
implementation.
