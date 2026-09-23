# Auto-G16 v3 acceptance: observe

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:930-1025 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-OBS-MIN-CONTRACT-01: Minimal Read-Only Observe

**Status: CONTRACT FREEZE CANDIDATE; IMPLEMENTATION NOT AUTHORIZED.** The
candidate must satisfy all of the following without product code, selector
mutation, Core/API/schema change, transport, or live observation:

1. The only future public package is `auto_g16.observe`, focused tests belong
   under `tests/v3/observe/`, and the public inventory is exactly the six names
   frozen in `boundary-spec.md`.
2. `AttemptObservation` and `AttemptObservationProjection` have the exact
   immutable fields and types in the frozen contract; the record identity is
   not caller-selectable and the projection is never persisted as authority.
3. The UUIDv5 root/domain constants and compact ordered-array JSON encoding
   reproduce the frozen normative identity on Python 3.11 through 3.13.
   Boolean progress, a negative position, a noncanonical timestamp, unknown
   source kind, invalid freshness, invalid state/source pairing, or extra field
   fails closed.
4. Recording requires one exact existing Core Attempt. Missing and
   cross-Attempt bindings fail before append; no Task, Attempt, Result,
   CalculationPlan, Workflow, or Execution record is mutated.
5. Recording produces one exact public Core `Observation` of type
   `auto-g16-v3-attempt-observation`, with matching IDs and no hidden or extra
   payload fields. It creates no Observe database or Core migration.
6. Exact same-ID/same-payload replay is idempotent. Same-ID/different-payload,
   forged identity, malformed matching Core data, and unexpected source/state
   combinations conflict or fail closed.
7. Reopening the Core store retains every Observe record in append order and
   produces the same projection and `observation_count`.
8. Non-Observe Core observations are ignored, while every matching Observe
   record is validated before any view is returned; an older malformed record
   cannot be hidden by a later valid record.
9. Scheduler, process, and Gaussian records are projected independently. The
   last appended valid record per axis wins; wall-clock order and caller input
   order cannot replace Core append order.
10. Freshness and observed state are independent axes. The last appended valid
    record replaces the earlier record, but a known `state` remains known when
    `freshness=stale`; staleness alone never becomes state `unknown`. Explicit
    state `unknown` remains unknown with either fresh or stale evidence. With no
    usable record for an axis, its `None` slot is the no-evidence UNKNOWN case
    and is distinct from a known source state `absent`.
11. Queued, held, running, exiting, repeated progress, unchanged position,
    stale evidence, and a slow or long-running job are observations, not
    failures.
12. Scheduler `terminal` or `absent` never means Gaussian completion or
    scientific acceptance. Process `absent` never means failure. Gaussian
    `termination` never distinguishes normal/error and never creates a Result.
13. `unknown` remains explicit and creates no retry, replacement,
    recovery-child, submission, cancellation, cleanup, or effect authority.
14. Recording and projection produce zero qstat/ps calls, filesystem or log
    reads, SSH/transport, PBS/Gaussian calls, Core state transitions, Workflow
    decisions, Result parsing, ScientificValidation, or acceptance.
15. Source identity and source-classified freshness are preserved exactly but
    are not treated as self-authenticating transport or acquisition evidence.
    Observe does not recompute freshness from ambient time.
16. Dependency tests prove `Observe -> Core` only: Core, Execution, Result,
    Approval, Workflow, and ScientificValidation never import Observe.
17. Narrow reuse evidence records `PORT`, `EXTRACT`, `WRAP`, `REWRITE`, `DROP`,
    and `DEFER`; the `REWRITE` reason names the legacy acquisition/governance
    coupling, and no v2 owner/receipt/capability/hash-lineage object becomes v3
    runtime authority.
18. Explicit non-goals cover full stall/failure diagnosis, resource telemetry
    or planning, retry/repair, live acquisition, OpenSSH/RTwin/PBS/Gaussian,
    qsub/qdel, deployment, Result/scientific policy, ReviewBundle, `EXEC-02`,
    and all live work.

The freshness/state contract cases are exact:

| Latest usable axis evidence | Projected meaning |
| --- | --- |
| scheduler `running` + `stale` | known `running`, stale; not `unknown` or failed |
| scheduler `queued` + `stale` | known `queued`, stale; not `unknown` or failed |
| explicit state `unknown` + `fresh` | unknown state with fresh evidence |
| explicit state `unknown` + `stale` | unknown state with stale evidence |
| no usable record for the axis | `None`, the no-evidence UNKNOWN projection |
| same known state with freshness changed only | state is preserved; freshness and record identity change |

Every row grants zero failure, retry, replacement, recovery-child, submission,
qsub, qdel, cancellation, cleanup, or other effect authority. A malformed
matching record still fails projection closed and is not silently reclassified
as unknown.

The later implementation acceptance matrix must use only synthetic Core
records and must include: one event for each closed state; mixed-axis append
order; same-time different-source records; timestamp reversal; exact replay;
identity conflict; missing/cross Attempt; malformed old and latest rows;
durable reopen; `running+stale`; `queued+stale`; explicit `unknown+fresh` and
`unknown+stale`; no-evidence UNKNOWN; freshness-only change preserving known
state; non-Observe coexistence; slow running and unchanged progress; scheduler
terminal/process absent/Gaussian termination separation; stale-known producing
neither failure nor retry/effect authority; and a zero-call effect spy. No live
fixture is permitted.

V30-OBS-MIN-CONTRACT-01 stops after a new independent adversarial contract
review. Completion authorizes neither publication, `V30-VAL-OBS-01`, Observe
implementation, `V30-EXEC-02`, nor live work.
