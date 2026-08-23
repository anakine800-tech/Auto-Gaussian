# Auto-G16 v3 Acceptance Cases

These are feature-expansion stop conditions, not authority for a live run.

## V30-CORE-01: Clean Runtime Core

**Status: SATISFIED.** Final Core Review is PASS and `V30-CORE-01 = COMPLETE`.

The Core Interface Review milestone is **PASS WITH CONDITIONS**. The
`auto_g16.core` public path, the ten immutable keyword-only domain records, and
their field-level interface are approved. Canonical payload encoding is a
private implementation detail, not a public symbol, constructor annotation,
runtime payload value, or compatibility promise. Public payload fields expose
only a deeply immutable semantic mapping view. `ExecutionSnapshot` remains
excluded.

The following satisfied conditions remain the frozen V30-CORE-01 acceptance
contract for Python 3.11 or newer:

1. A dependency-free `SQLiteRuntimeStore` persists and reloads all ten Core
   record types. It uses SQLite foreign keys, a versioned fresh-database schema,
   explicit transactions, and no implicit migration of an unknown schema. On
   reopening schema version 1, Core verifies the exact owned schema identity,
   including columns, primary and foreign keys, uniqueness, checks, and indexes;
   same-named counterfeit tables fail closed.
2. Immutable record insertion is replay-safe: an exact repeat is idempotent,
   while the same record identity with different content fails closed without
   overwriting the stored value.
3. Every stored `Attempt` starts in `PLANNED`. Its only states are `PLANNED`,
   `SUBMISSION_INTENT_RECORDED`, `SUBMITTED`, `UNKNOWN`, `RUNNING`, `SUCCEEDED`,
   `FAILED`, and `NOT_SUBMITTED`. State changes outside the documented store
   operations fail closed and leave the transaction unchanged.
4. `record_submission_intent` atomically records exactly one caller-supplied
   intent identity and moves `PLANNED -> SUBMISSION_INTENT_RECORDED`. Exactly
   one concurrent caller receives the explicit `WINNER` claim signal that may
   gate an external submission; exact replay receives the distinct `REPLAY`
   signal and cannot be mistaken for that gate. Implicit truth-value use fails
   closed, requiring an explicit `WINNER` comparison. Reusing an intent identity
   for another Attempt, or a different identity for the same Attempt, is a
   conflict. Core never invokes submission itself.
5. `record_submission_outcome` binds the recorded intent to exactly one
   `SUBMITTED` or `UNKNOWN` outcome. Exact replay is idempotent; conflicting
   outcomes fail. `UNKNOWN` never authorizes retry.
6. Reconciliation of `UNKNOWN` requires a persisted `Observation` for the same
   Attempt. `UNRESOLVED` preserves `UNKNOWN`; terminal evidence may resolve it
   once to `SUBMITTED` or `NOT_SUBMITTED`. Direct or conflicting reconciliation
   fails closed.
7. Normal execution progress permits only `SUBMITTED -> RUNNING`,
   `SUBMITTED -> SUCCEEDED|FAILED`, and `RUNNING -> SUCCEEDED|FAILED`.
   `SUCCEEDED`, `FAILED`, and `NOT_SUBMITTED` are terminal in this slice.
8. Each Task has exactly one persisted root `Attempt`; a second parentless
   Attempt fails closed regardless of the root state. A child `Attempt` is
   created only by an explicit call after its parent is `FAILED` or
   `NOT_SUBMITTED`. It preserves the same `task_id`, records the parent identity,
   has a strictly greater positive ordinal, and is a new `PLANNED` Attempt.
   Core never creates a child automatically, and an `UNKNOWN` parent cannot
   have one or be bypassed by another root.
9. `Observation` and `Result` records are append-only, require an existing
   Attempt, survive close/reopen, retain deterministic insertion order, and
   use the same exact-replay/conflicting-identity rule. Their payload storage
   encoding remains private.
10. Public Core has no Transport, PBS, Gaussian, deployment, scheduler query,
    retry executor, cleanup, or `ExecutionSnapshot` behavior. Focused and
    adversarial tests under `tests/v3/core/` include real concurrent intent
    claim, UNKNOWN root-bypass, counterfeit-schema, and private-encoding
    counterexamples. Syntax compilation, static source checks, and
    `git diff --check` pass offline.

All conditions are satisfied. V30-CORE-01 stops at this boundary; completion
does not authorize another v3 slice.

## V30-3A: Approval Authority and Invalidation Contract

**Status: SATISFIED / INTEGRATED ON
`main@4a181871b0894161dd74fe91c405aa35e3691fd6`.** The conditions below
remain the frozen approval authority contract. They require no Core API/schema
change and perform no external effect:

1. Scientific Approval binds the exact CalculationPlan ID, task, positive
   revision, expanded canonical intent, displayed semantic meaning, explicit
   approved decision, and reviewer identity/evidence. Exact unchanged replay
   is deterministic and idempotent; conflicting content under the same evidence
   identity fails closed.
2. A different CalculationPlan ID, revision, task binding, canonical intent,
   or displayed semantic meaning makes the prior Scientific Approval
   inapplicable to the changed plan.
3. Manual input editing is reparsed into the current semantic plan, displays
   the semantic diff, and requires approval for that current plan. Matching
   artifact hashes alone cannot keep or create approval.
4. Resource, profile/target, workspace, PBS-template, or ExecutionSnapshot
   change is not automatically classified as a scientific change and cannot
   silently modify the approved CalculationPlan.
5. Batch Submit Approval contains an exact finite non-empty list of existing
   Attempts, an explicit approved decision, and reviewer identity/evidence.
   Each member binds its exact task, CalculationPlan ID/revision, and current
   Scientific Approval; one review may approve multiple exact members.
6. An Attempt not listed in the exact set is rejected. Batch identity, a
   prefix/query/range, a future placeholder, or later Batch membership cannot
   expand the approved set.
7. A replacement or recovery-child Attempt is rejected by the parent's Batch
   Submit Approval. A child always requires new explicit membership; the exact
   unchanged Scientific Approval may remain applicable only when the child's
   plan binding is identical.
8. Batch Submit Approval is not a transaction. Failure, `UNKNOWN`, or
   non-submission of one member grants no replacement/retry authority and does
   not expand another member's scope.
9. Exact Operational Confirmation binds one exact ExecutionSnapshot, explicit
   human confirmation and confirmer identity/evidence, plus all nested
   effect-relevant input, resource, profile/target, workspace, PBS-template,
   adapter-contract, Attempt, and submission-intent semantics.
10. Exact unchanged Operational Confirmation replay is deterministic and
    non-effectful. Any snapshot or nested binding change makes the prior
    confirmation stale and is rejected before a Core claim or external effect.
11. Scientific Approval alone, Batch Submit Approval alone, and Exact
    Operational Confirmation alone each produce zero Core transitions and zero
    filesystem, transport, scheduler, PBS, or Gaussian effects.
12. The complete current approval chain still produces zero submission effect
    unless the exact Core claim returns explicit `WINNER`; `REPLAY`, rejection,
    and every non-winner path make zero adapter/effect calls.
13. Missing, malformed, conflicting, cross-Attempt, cross-plan, stale, or
    cross-snapshot evidence fails closed before Core claim and effect.
14. `UNKNOWN` never creates scientific, Batch Submit, confirmation, child, or
    retry authority and permits only the frozen read-only same-Attempt
    reconciliation path.
15. Approval evidence may use hashes for artifact identity or audit, but no
    hash, receipt, legacy owner-chain, capability, or lineage record substitutes
    for semantic replay of the three current approval gates.
16. Contract tests for V30-3B must cover plan-change staleness, unchanged replay,
    unlisted and future-child rejection, exact multi-Attempt membership,
    snapshot-change staleness, zero-effect isolated approvals/confirmation,
    explicit `WINNER`, and UNKNOWN no-retry behavior.
17. Approval implementation is owned by `auto_g16.approval`, with focused tests
    under `tests/v3/approval/`. It may depend on public Core and Execution
    surfaces; neither Core nor Execution imports the approval layer, and no
    approval record or state is added to the Core schema.

V30-3A stops after independent contract review and repository publication.
V30-3B implementation is integrated without changing these conditions;
completion does not authorize V30-EXEC-02, deployment, or live execution.

## V30-EXEC-01: Frozen Offline Execution Boundary

**Status: SATISFIED / INTEGRATED ON
`main@2911451eb91a63c4c1df7601b4ac49610b6205a3`.** The numbered conditions
below remain the acceptance contract; integration grants no SSH, RTwin, PBS,
Gaussian, deployment, or other live-effect authority:

1. Semantically identical snapshots keep one identity across JSON key order or
   formatting changes.
2. Any effect-relevant field change produces a new snapshot identity.
3. Mutable ServerProfile changes stale an unexecuted snapshot and require fresh
   resolution.
4. Windows relative, home-relative, and `~` paths are rejected.
5. POSIX relative or non-canonical paths are rejected.
6. PBS template identity derives from exact bytes; an opaque caller ID is
   rejected.
7. `PreparedInputBinding` binds exact prepared bytes durably to the
   CalculationPlan, revision, and Attempt.
8. `ResolvedResourceRequest` binds the exact ResourceSpec and effect-time
   values while remaining separate from scientific intent.
9. An existing Project can receive a fresh Attempt workspace.
10. Local, RTwin, and server workspaces are Attempt-specific, contained,
    no-follow where effectful, and no-overwrite.
11. Partial workspace allocation persists explicitly and never masquerades as
    globally no effect.
12. Concurrent claims yield exactly one Core `WINNER` for a submission intent
    and at most one submission call for the Attempt.
13. `REPLAY` makes zero adapter or external-effect calls.
14. Pre-effect failure records no-effect evidence and is not `UNKNOWN`.
15. Possibly effectful submission ambiguity becomes `UNKNOWN`.
16. `UNKNOWN` permits same-Attempt reconciliation, never automatic retry.
17. Minimal `RemoteEffectReceipt` replay is idempotent and conflicting content
    is rejected; all three frozen effect states and `effect_sequence` are
    covered.
18. The RTwin synthetic adapter needs no real SSH, PBS, or Gaussian.
19. Core remains transport-free.
20. No `qdel`, cancellation, deletion, cleanup, deployment, or live behavior is
    exercised or authorized.

## V30-RESULT-01: Frozen Result Provenance Boundary

**Status: SATISFIED / INTEGRATED ON
`main@2911451eb91a63c4c1df7601b4ac49610b6205a3`.** The numbered conditions
below remain the acceptance contract and do not grant scientific acceptance or
live-effect authority:

1. UUIDv5 namespaces are source-controlled and caller-invariant.
2. Exact replay of the input tuple (`attempt_id`, `calculation_plan_id`,
   `calculation_plan_revision`, `prepared_input_binding_id`,
   `execution_snapshot_id`) produces the same identity.
3. A changed plan revision, prepared input binding, or snapshot identity
   produces a new input-binding identity.
4. Malformed envelope metadata fails closed without a false legal envelope.
5. A valid complete envelope persists under the exact tuple
   (`attempt_id`, `input_binding_observation_id`, `capture_source_id`,
   `capture_manifest_sha256`, `capture_completeness`).
6. A valid partial envelope persists and remains explicitly incomplete.
7. A valid envelope with unparseable output is preserved with an explicit
   `unparseable` Result outcome.
8. `unsupported` output or parser status remains distinct from malformed
   metadata.
9. Exact Result tuple (`envelope_observation_id`, `parser_name`,
   `parser_version`, `result_kind`) replay is idempotent.
10. The same Result identity with a different payload conflicts.
11. A new parser version produces a new Result identity without overwriting the
    earlier result.
12. Multiple captures remain append-only.
13. A Result never splices facts or provenance across captures.
14. The current view chooses the latest legal complete capture by deterministic
    insertion order.
15. With no complete capture, the current view exposes the latest partial
    capture as explicitly incomplete.
16. Durable incomplete prefixes survive close and reopen.
17. Result creation and reading never change Attempt runtime state.
18. Result existence and parser status do not grant scientific acceptance.
19. Synthetic artifacts require no live RTwin or PBS.
20. Core API and schema remain unchanged.

## V30-RESULT-SECTION-ATTRIBUTION: Additive Gaussian Job Facts

**Status: CONTRACT FROZEN; IMPLEMENTATION NOT AUTHORIZED.** These conditions
extend Result additively and leave `GaussianLogParser` v1 and historical
`gaussian-log-facts` outcomes unchanged. They grant no ScientificValidation,
scientific-acceptance, execution, transport, retry, or live authority:

1. `GaussianLogParser` remains exactly `auto-g16-v3-gaussian-log` / `1.0.0` /
   `gaussian-log-facts`; existing stored v1 rows reopen byte-semantically
   unchanged and receive no migration, reinterpretation, backfill, or update.
2. The additive public `GaussianJobParser` is exactly
   `auto-g16-v3-gaussian-job` / `1.0.0` / `gaussian-job-facts` and uses the
   source-controlled grammar ID `auto-g16-v3-gaussian-job-grammar/1`.
3. `ParseOutcome` retains outer schema version 1, exact fields, and Result
   UUIDv5 identity over envelope, parser name, parser version, and result kind.
   Old and new parser outcomes for one envelope coexist append-only with
   distinct identities.
4. Facts validation dispatches only on the complete exact parser tuple. The
   new recursive facts schema is closed at version 1; unknown/missing keys,
   type drift, bad enums, inconsistent derived values, or an unknown tuple
   fails on construction and durable reopen.
5. Exact unchanged bytes, envelope, parser tuple, and grammar reproduce the
   same outcome identity and payload. A changed capture or parser version
   produces a new identity; the same identity with different facts or spans
   conflicts.
6. A clean complete single Opt/Freq job with structurally valid transitions,
   attributed terminal/optimization/stationary/frequency records, and complete
   recognized geometry blocks produces `PARSED` facts deterministically.
7. A partial OutputEnvelope produces `PARTIAL` and empty facts regardless of
   recognizable prefixes. No complete OutputEnvelope produces `PARTIAL`.
8. Two or more structurally proven jobs, including a genuine Link1 job,
   produce `UNSUPPORTED` with no last/frequency/optimization/normal-job
   selection.
9. A complete capture with a truncated job boundary, malformed transition,
   contradictory structure, no safely recognized job, or ambiguous context
   produces `UNPARSEABLE`; ambiguous bytes never produce `PARSED`.
10. Titles containing `Optimization completed` or `Stationary point found`
    produce no marker facts. Mixed echo plus a real machine-output marker
    attributes only the real marker.
11. A title containing `Frequencies -- -123.4` produces no frequency block or
    imaginary-frequency fact. A valid machine-output frequency block is
    emitted with its exact source span and ordered finite values.
12. Input, molecular specification, title, or comment echo containing `Normal
    termination of Gaussian` or `Error termination` creates no terminal fact.
    False echo termination before a genuine terminal record does not alter the
    attributed program status.
13. Fake `--Link1--`, `Entering Link 1`, or equivalent job text in an echo
    region does not create a second job. A genuine structurally validated
    Link1 transition does.
14. An empty, malformed, non-finite, wrong-cardinality, truncated, overlapping,
    or context-invalid recognized frequency block makes a complete capture
    `UNPARSEABLE`; no good token or other block is selected as fallback.
15. Frequency blocks are ordered by zero-based half-open byte span. The
    top-level frequency tuple is their exact ordered concatenation; total and
    imaginary counts agree and no scientific minimum rule is applied.
16. Every complete recognized input- or standard-orientation block is emitted
    in byte order with `angstrom` units, its exact span, contiguous one-based
    centers, integer atomic numbers `0..118`, and finite Cartesian coordinates.
17. A recognized malformed, truncated, mixed, non-contiguous, non-finite, or
    incomplete orientation block makes a complete capture `UNPARSEABLE`; the
    parser neither skips it nor falls back to another geometry.
18. Atomic number `0` is preserved as a dummy-center Result fact. Result does
    not infer an element or minimum; downstream ScientificValidation must treat
    the dummy-containing geometry as unsupported.
19. Every span is a zero-based half-open byte interval within the exact bound
    Gaussian-log artifact. Every evidence span lies within the one job-section
    span, repeated evidence is ordered, and impossible overlaps fail closed.
20. A span bound to another envelope, artifact logical name/kind, SHA-256, or
    size; outside the artifact or job section; reversed; empty; unordered; or
    otherwise impossible fails before append and on reopen.
21. `ResultProvenanceService` proves the exact same-Attempt envelope and
    artifact tuple, span containment/order, exact parser-tuple validator, and
    recomputed Result identity when recording and reopening attributed facts.
22. A structurally valid persisted outcome whose evidence ID is reused with
    different source spans conflicts under the existing append-only rule.
23. A valid parsed error-termination job and a valid parsed normal-termination
    job each expose exactly one context-attributed terminal item and zero of
    the other kind. Missing, repeated, malformed, or contradictory terminal
    structure is `UNPARSEABLE`, not a favorable status.
24. SCF energy and thermochemistry values are finite, ordered, context-local
    facts with attributed spans; raw echo or malformed values never become
    authoritative facts.
25. A new `gaussian-job-facts` outcome and an old `gaussian-log-facts` outcome
    may coexist for the same exact envelope. ScientificValidation must reject
    the old tuple as insufficient attributed evidence rather than converting
    or merging it.
26. A Result never splices a job section, marker, frequency, geometry,
    termination, energy, or thermochemistry span across captures, envelopes,
    artifacts, Attempts, parser versions, or result kinds.
27. Grammar behavior is pure and deterministic from exact bytes. Locale,
    decoding replacement, line-ending rewrite, filesystem order/mtime,
    runtime process state, checkpoints, caller hints, and nondeterministic
    heuristics cannot select a context or fact.
28. Result exposes generic attributed facts only. It never labels a geometry a
    minimum, emits `VALIDATED_MINIMUM` or `NOT_MINIMUM`, decides scientific
    acceptance/rejection, or mutates Attempt state.
29. Focused implementation evidence must cover all echo-injection, fake/genuine
    Link1, status-matrix, malformed-block, all-geometry, span-forgery,
    coexistence/reopen, identity-conflict, and cross-capture cases above using
    synthetic exact bytes with no SSH, PBS, Gaussian, or live action.
30. Core API/schema and the frozen Execution, Approval, and Workflow contracts
    remain byte-identical; implementation requires a separate Owner Gate and
    precedes resumption of the paused ScientificValidation contract.
31. LF and CRLF fixtures tokenize without normalization. Every expected
    `line_start`, `content_end`, `line_end`, job span, and evidence span is
    hard-coded against the original fixture bytes; a final complete terminal
    line without a terminator ends at artifact size and remains deterministic.
32. The literal/regex anchors and FSM transition table in `boundary-spec.md`
    are exhaustive authority. Two matching transitions, an omitted required
    transition, a lone CR, or a spoofed/ambiguous echo boundary is
    `UNPARSEABLE`; no implementation priority or heuristic resolves it.
33. Artifact bytes are checked before the cardinality matrix. Name-set, type,
    byte-size, or SHA mismatch raises `MalformedEnvelopeError`; partial capture
    with zero/one/many Gaussian logs is `PARTIAL`, while complete capture with
    zero/many is `UNSUPPORTED` and complete capture with one runs the grammar.
34. A parsed payload has empty diagnostics. Every non-parsed payload has empty
    facts and exactly one closed primary diagnostic code selected by strict
    left-to-right fail-fast production ownership; free-form prose is not
    persisted and there is no diagnostic ranking/tie pass.
35. Two independent implementations given identical exact inputs produce the
    same status, singleton diagnostic or empty diagnostics, job/evidence spans,
    primary failure position/span (or matrix no-position), source ordering,
    facts, complete payload, and Result identity.
36. Once a legal parent opener admits an optimization, frequency, or geometry
    child, that child owns the first subsequent failure. FSM legality precedes
    row shape, field designation/count, left-to-right numeric fields, and block
    closure; a parent block never replaces or accompanies a child row/numeric
    diagnostic.
37. `unparseable-orphan-anchor` requires an exact otherwise-valid named anchor
    in an illegal non-echo FSM state. A malformed lookalike is never orphaned;
    outside an admitted child it follows the closed malformed-prefix rule.
38. In an active frequency value production, valid prefix/separators/count plus
    `NaN` is uniquely `unparseable-numeric-token`; wrong prefix/separator/count
    or missing continuation/closure is uniquely
    `unparseable-frequency-block`.
39. In `GEOM_ROWS`, wrong field count or valid-integer center/range violation is
    `unparseable-geometry-row`; correct six-field shape plus the first invalid
    numeric token is `unparseable-numeric-token`; wrong header/separator/closure
    is `unparseable-geometry-block`.
40. EOF is owned only by the active production: preamble, echo, optimization,
    frequency, geometry, and required-terminal states select their one frozen
    EOF code. EOF never synthesizes an orphan, row, or numeric failure.
41. Capture/artifact validation and the cardinality matrix run before grammar.
    A matrix `PARTIAL`/`UNSUPPORTED` outcome emits its one matrix code and does
    not run grammar; artifact identity mismatch raises `MalformedEnvelopeError`
    with no `ParseOutcome` diagnostic.
42. Each legal thermochemistry candidate is evaluated in the exact order
    structure, canonical key, numeric lexical grammar, finite conversion,
    duplicate check against previously committed same-key evidence, then
    commit. A later stage is never evaluated after an earlier failure.
43. A second structurally valid same-key line with `NaN`, `Inf`, or another
    token outside the closed numeric grammar is only
    `unparseable-numeric-token` at the exact bad token. A structurally malformed
    second same-key candidate is only its existing structural diagnostic. In
    both cases duplicate checking is never reached and the current line never
    enters the committed seen-key set.
44. A fully valid second occurrence of a previously committed canonical
    thermochemistry key is only `unparseable-duplicate-evidence`, whether the
    numeric value is equal or different. Its conformance span is the full
    current duplicate line `[line_start,line_end)`, including LF or CRLF when
    present and ending at artifact length for a final unterminated line. The
    first occurrence remains the committed fact and the duplicate is not
    committed.
45. Duplicate tracking is scoped to the one supported Gaussian job represented
    by one `GaussianJobParser` outcome. Canonical-key equality alone controls
    it; raw spelling, display label, numeric value, whitespace, source span,
    other jobs, captures, parser outcomes, Attempts, and repository history do
    not. Malformed or numerically invalid candidates never create seen-key
    state.

The future implementation fixture matrix is mandatory and uses synthetic or
release-cleared bytes only. Tests hard-code expected raw-byte offsets; deriving
expected offsets by calling the parser under test is forbidden.

| Fixture | Exact expected outcome |
| --- | --- |
| clean single Opt/Freq, LF | `PARSED`; exact LF job/evidence offsets; all geometry/frequency blocks |
| byte-equivalent clean transcript, CRLF | `PARSED`; offsets include both CRLF bytes and differ mechanically from LF |
| complete terminal line without final newline | `PARSED`; terminal and job end equal artifact size |
| truncated terminal content | `UNPARSEABLE` / `unparseable-terminal` |
| missing terminal | `UNPARSEABLE` / `unparseable-terminal` |
| legal terminal followed by blank lines | unchanged `PARSED`; job span ends at terminal, not trailing blanks |
| legal terminal followed by nonblank bytes | `UNPARSEABLE` / `unparseable-trailing-content` |
| lone CR in complete artifact | `UNPARSEABLE` / `unparseable-line-terminator` |
| echoed optimization/stationary/frequency/normal/error strings | `PARSED`; zero false evidence; real machine records alone contribute |
| fake `--Link1--`, `JOB_START`, or `Entering Link 1` in echo | one job; zero multi-job effect |
| genuine `LINK1_LITERAL` or `INTERNAL_JOB_STEP` in machine body | `UNSUPPORTED` / `unsupported-multiple-job` |
| two genuine `JOB_START` records | `UNSUPPORTED` / `unsupported-multiple-job` |
| complete capture, zero Gaussian logs | `UNSUPPORTED` / `unsupported-gaussian-log-cardinality` |
| complete capture, one Gaussian log | exact grammar result |
| complete capture, multiple Gaussian logs | `UNSUPPORTED` / `unsupported-gaussian-log-cardinality` |
| partial capture, zero/one/multiple Gaussian logs | `PARTIAL` / `capture-partial`; empty facts |
| artifact name-set/size/SHA mismatch | `MalformedEnvelopeError`, no ParseOutcome |
| active valid-shape frequency row with malformed or non-finite numeric token | `UNPARSEABLE` / `unparseable-numeric-token`; no frequency facts |
| wrong-cardinality or truncated frequency state sequence | `UNPARSEABLE` / `unparseable-frequency-block`; no frequency facts |
| active `FREQ_VALUES`, exact `Frequencies --` shape, token `NaN` | only `unparseable-numeric-token`; conformance span is the exact `NaN` token |
| active `FREQ_VALUES`, wrong prefix/separator/cardinality | only `unparseable-frequency-block` |
| exact `STATIONARY` in an illegal non-echo FSM state | only `unparseable-orphan-anchor`; conformance span is the full anchor line |
| active optimization row with valid shape and numeric token `NaN` | only `unparseable-numeric-token` |
| active optimization child with wrong required row/marker sequence | only `unparseable-optimization-block` |
| `MACHINE_BODY` line ` -- Stationary point found` (missing the required period), before any child is admitted | only `unparseable-malformed-prefix`, never orphan |
| fake anchor-like line while a required child structural line is active | only that child's block code, never orphan |
| malformed grammar-bearing SCF/thermo/optimization/frequency/geometry/terminal prefix in machine context | its one exact closed prefix/direct-production diagnostic; no partial fact |
| one and multiple valid orientation tables | `PARSED`; every table and exact heading-to-closing-separator span emitted |
| valid geometry opener + malformed required header | only `unparseable-geometry-block` |
| geometry row with five/seven fields | only `unparseable-geometry-row`; conformance span is the full row line |
| six-field geometry row with coordinate `NaN` | only `unparseable-numeric-token` |
| valid geometry rows followed by a separator-family line shorter than five hyphens | only `unparseable-geometry-block` |
| valid geometry rows + EOF before closing separator | only `unparseable-geometry-block` |
| noncontiguous center or atomic number outside `0..118` | only `unparseable-geometry-row` |
| earlier malformed geometry row + later malformed frequency token | only the geometry diagnostic; later bytes have no authority |
| one valid-shape line with multiple invalid numeric fields | only the leftmost invalid token; displayed field order breaks an equal-start tie |
| first valid thermochemistry key + second same key with `NaN` | `UNPARSEABLE`; only `unparseable-numeric-token`; exact second-line `NaN` token span; duplicate check not reached |
| first valid thermochemistry key + second same key with `Inf` | `UNPARSEABLE`; only `unparseable-numeric-token`; exact second-line `Inf` token span; duplicate check not reached |
| first valid thermochemistry key + second structurally malformed same-key candidate | `UNPARSEABLE`; only the existing structural-production diagnostic; duplicate check not reached |
| first valid thermochemistry key + identical fully valid second value | `UNPARSEABLE`; only `unparseable-duplicate-evidence`; full second-line span; second value not committed |
| first valid thermochemistry key + different fully valid second value | `UNPARSEABLE`; only `unparseable-duplicate-evidence`; full second-line span; second value not committed |
| first same-key candidate has an invalid numeric token + later valid same-key line | `UNPARSEABLE`; only the first `unparseable-numeric-token`; later line is not examined and no duplicate exists |
| fully valid duplicate thermochemistry line terminated by LF | `UNPARSEABLE`; only `unparseable-duplicate-evidence`; span is the full current line including LF |
| fully valid duplicate thermochemistry line terminated by CRLF | `UNPARSEABLE`; only `unparseable-duplicate-evidence`; span is the full current line including both CRLF bytes |
| fully valid duplicate thermochemistry line is final and unterminated | `UNPARSEABLE`; only `unparseable-duplicate-evidence`; full current-line span ends at artifact size `L` |
| two fully valid different canonical thermochemistry keys | no duplicate diagnostic; each is committed in byte order |
| EOF in `PREAMBLE` / echo / optimization / frequency / geometry / `MACHINE_BODY` | respectively job-start / echo-boundary / optimization-block / frequency-block / geometry-block / terminal; conformance span follows the frozen final-consumed-line/no-span rule |
| same exact bytes parsed twice | byte-identical payload and Result identity |
| old v1 and new parser on the same envelope | distinct append-only identities; old facts never treated as attributed |
| changed parser version or capture | distinct Result identity |
| forged cross-envelope/artifact/out-of-range/reordered/overlapping span | reject before append and again on reopen |
| same Result ID with different spans | append conflict; no overwrite |

## V30-MIN-VALIDATE-CONTRACT-01: Minimum Scientific Validation

**Status: CONTRACT FROZEN / INTEGRATED; IMPLEMENTATION NOT AUTHORIZED.** These
conditions freeze the minimum post-Result nonlinear-minimum and human
acceptance boundary. They grant no product, selector, Core/Result/Approval/
Execution/Workflow change, Observe, ReviewBundle, `V30-EXEC-02`, or live
authority:

1. `auto_g16.scientific_validation` is the sole future public owner and
   `tests/v3/scientific_validation/` its focused-test package. Its product
   dependency is only public Result and Core, and neither upstream layer
   imports it.
2. ScientificValidation accepts no Gaussian path or artifact bytes, opens no
   output, runs no Gaussian regex, reconstructs no missing fact, and performs
   no raw-substring or raw-context interpretation.
3. Only `auto-g16-v3-gaussian-job` / `1.0.0` / `gaussian-job-facts` may support
   minimum classification. Legacy `gaussian-log-facts`, unknown tuples, and a
   Result with `ParseStatus.UNSUPPORTED` are `UNSUPPORTED`, never converted,
   merged, backfilled, or reparsed.
4. The exact plan/revision -> Attempt -> same-Attempt InputBinding -> COMPLETE
   OutputEnvelope -> same-envelope ParseOutcome/result ID -> policy/version
   chain is replayed through public records. Latest/current lookup and evidence
   splicing across captures, envelopes, Results, parsers, or Attempts rejects.
5. A supported `PARSED` fact mapping must bind every relied-upon span to the
   exact Result source artifact, envelope, job section, logical name, kind,
   size, and SHA-256. Partial/unparseable evidence, malformed provenance, or a
   missing supported fact is `INCOMPLETE`.
6. A normal classification requires exactly one attributed normal terminal
   fact and no error terminal fact. Attributed error termination is
   `INCOMPLETE`, never `NOT_MINIMUM` or `VALIDATED_MINIMUM`.
7. Optimization and stationary evidence tuples are non-empty and equal in
   length, pair by index, and close in strict source order. The final pair is
   the accepted pair; missing, unequal, interleaved, or ambiguous pairing is
   `INCOMPLETE`.
8. Final optimized geometry is the unique rightmost complete Result geometry
   block whose span ends at or before the accepted optimization marker begins.
   Selection uses spans only. No orientation preference, nearest-looking block,
   file/checkpoint fallback, tie, overlap, or raw-output search is allowed.
9. Frequency evidence is the complete ordered suffix of all Result frequency
   blocks starting at or after the accepted stationary span ends. Every block
   and value in that suffix is used; no favorable subset, regrouping, or second
   raw analysis exists.
10. The selected geometry has `N >= 3` atoms and no atomic-number-zero center.
    `N < 3` or a dummy center is `UNSUPPORTED`; no atom is removed or inferred.
11. V3.0 uses exactly `3*N - 6` modes and performs no linearity tolerance or
    geometry classification. Fewer selected modes is `INCOMPLETE`; more is
    `UNSUPPORTED`; exactly that count is supported for minimum classification.
12. Every selected finite frequency `< 0.0` is imaginary and every value
    `>= 0.0` is not. Exactly one negative on otherwise complete supported
    evidence is `NOT_MINIMUM`; zero negatives is `VALIDATED_MINIMUM`.
    Consequently `-1e-12` is imaginary and `0.0` is not.
13. The four and only machine classifications are `VALIDATED_MINIMUM`,
    `NOT_MINIMUM`, `INCOMPLETE`, and `UNSUPPORTED`. No probable, warning,
    partial, tolerance, or caller-defined class exists.
14. One domain-separated UUIDv5 outcome binds the complete canonical chain,
    selected expanded facts/spans, exact policy, classification, and exactly
    one primary reason code from the closed ordered table in
    `boundary-spec.md`. The first applicable row owns the outcome; no secondary
    reason collection or ordering choice exists. Exact replay is identical;
    conflicting same-ID content fails; changed Result or policy produces a new
    identity.
15. ScientificValidation-owned schema-v1 SQLite persistence is append-only and
    separate from Core/Result. Create is fresh/no-overwrite, reopen is
    terminal-no-follow and replacement-safe, exact replay is idempotent,
    conflicting replay and unexpected schema fail closed, and durable reopen
    reproduces typed records and deterministic order.
16. `ScientificAcceptance` is a separate deterministic immutable record for
    one exact persisted `VALIDATED_MINIMUM` only. A human cannot accept
    `NOT_MINIMUM`, `INCOMPLETE`, or `UNSUPPORTED`; acceptance never changes
    Result, Attempt, CalculationPlan, or MinimumValidationOutcome.
17. Validation, recording, acceptance, and replay make zero Core transition,
    workspace/artifact mutation, transport/scheduler/Gaussian call,
    submission, retry, recovery, cancellation, cleanup, or deletion. `UNKNOWN`
    creates no authority.
18. Two conforming implementations presented with the same closed Result and
    policy choose the same marker pair, geometry, complete post-stationary
    frequency suffix, classification, identity, and acceptance eligibility.

The public-shape closeout adds no public inventory and must satisfy all of the
following before implementation may be authorized:

1. Both public records have the one exact field/type inventory frozen in
   `boundary-spec.md`; neither an implementation nor caller can add an
   authority-bearing field.
2. Each deterministic identity field is `init=False` and is recomputed from
   every other authority field through the exact frozen UUIDv5 domain.
3. Schema version `1`, policy ID `auto-g16-v3-minimum-validation`, and policy
   version `1.0.0` are source-controlled and not caller-selectable.
4. Timestamp, path, temporary location, formatting, and opaque digest
   currentness do not enter authority identity.
5. Tagged canonical encoding distinguishes Boolean from integer values,
   rejects unsupported or non-finite values, and cannot depend on mapping
   insertion order.
6. Finite-float encoding and the complete canonical payload are deterministic
   on every supported Python minor.
7. Any selected evidence, policy, classification, or primary-reason change
   changes outcome identity; same-ID/different-payload replay conflicts.
8. `ScientificAcceptance` can bind only an exact persisted
   `VALIDATED_MINIMUM`; every other classification rejects before append.
9. Multiple reviewer acceptances remain separate explicit identities;
   `require_scientific_acceptance` requires both exact IDs and never chooses a
   latest/current record.
10. The four exact service signatures accept no artifact bytes, raw output,
    filesystem path, caller policy, parser callback, or latest-view selector.
11. The canonical-value algorithm is privately extracted without importing
    Workflow or private Core/Result identity helpers.
12. ScientificValidation persistence remains separate from Core and Result,
    with no upstream table, migration, API, or schema change.
13. The only public errors are the exact three-class hierarchy frozen in
    `boundary-spec.md`; a fourth error class fails the inventory check.
14. Both contract headings contain no candidate wording and retain
    `IMPLEMENTATION NOT AUTHORIZED` until the separate implementation gate.
15. The closeout changes no scientific policy, Result fact, parser grammar,
    validation precedence, effect, retry, Observe, ReviewBundle, or live
    boundary.

The independent adversarial review must answer these exact cases explicitly:

```text
raw Gaussian fact creation                         NO
legacy gaussian-log-facts validates a minimum     NO / UNSUPPORTED
cross-Result/capture/envelope splicing             NO
geometry selection from Result spans              YES / deterministic
frequency/stationary source ordering               YES / deterministic
error termination                                  INCOMPLETE
N < 3                                              UNSUPPORTED
atomic number 0                                    UNSUPPORTED
modes < 3*N-6                                      INCOMPLETE
modes > 3*N-6                                      UNSUPPORTED
exact modes and one negative                       NOT_MINIMUM
exact modes and zero negatives                     VALIDATED_MINIMUM
-1e-12 frequency                                   NOT_MINIMUM
0.0 frequency                                      non-imaginary
human accepts NOT_MINIMUM                          NO
ScientificAcceptance alters Result/Attempt         NO
implementation choice can change selected evidence NO
missing raw Gaussian interpretation remains        NO; otherwise STOP
```

Focused future evidence must also cover missing/unequal marker pairs, multiple
eligible geometries, pre-stationary frequencies, the full post-stationary
suffix, Result/source-span forgery, cross-source splicing, exact identity
replay/conflict, acceptance replay/conflict, fresh/reopen file integrity, and
durable order using synthetic records only. A combined missing marker,
geometry, and mode case must produce only `incomplete-marker-pair`; changing
the order or returning multiple reasons must fail contract tests. Contract
completion stops at the Publish Owner Gate and does not authorize
`V30-VAL-SCI-01` or implementation.

## V30-REVIEW-MIN-CONTRACT-01: Minimum Deterministic ReviewBundle

**Status: CONTRACT FREEZE CANDIDATE; IMPLEMENTATION WAIT.** These conditions
freeze the smallest v3.0 presentation/projection layer. They create no
ScientificAcceptance, execution authority, retry authority, product code,
selector change, external-viewer action, or live effect:

1. `auto_g16.review` is the sole future public package and
   `tests/v3/review/` its focused-test package. Its public inventory is exactly
   `ReviewAcceptanceState`, `ReviewBundle`, `ReviewBundleError`,
   `build_review_bundle`, and `render_review_bundle_json`.
2. Review depends only on public Core, Result, and ScientificValidation
   surfaces. It does not import Execution to reproduce snapshot semantics, and
   Core, Result, ScientificValidation, Approval, Execution, and Workflow never
   import Review.
3. The exact `ReviewBundle` field/type inventory in `boundary-spec.md` is
   immutable, keyword-only, service-created, and deeply closed. A caller
   cannot add an authority field or directly choose `review_bundle_id`.
4. The builder loads the exact persisted CalculationPlan, Attempt,
   MinimumValidationOutcome, and each explicitly named ScientificAcceptance;
   it proves the supplied InputBinding, OutputEnvelope, and ParseOutcome are
   exact persisted same-Attempt records rather than trusting a mapping copy.
5. The plan ID/revision/task, Attempt/task, InputBinding observation, envelope
   observation, parse Result ID/tuple, policy ID/version, and outcome binding
   must all close. Any missing, stale, or cross-plan/cross-Task/cross-Attempt/
   cross-input/cross-envelope/cross-Result/cross-policy/cross-outcome splice
   fails before projection.
6. InputBinding and OutputEnvelope must carry the same exact
   `execution_snapshot_id`. Review exposes that identity only; it does not
   reconstruct, authenticate, mutate, or reinterpret an ExecutionSnapshot.
7. `selected_final_geometry`, `selected_frequency_blocks`, and
   `selected_frequencies_cm1` are exact immutable copies of the persisted
   MinimumValidationOutcome fields. Review never reads raw Gaussian bytes,
   parses a span, chooses another geometry, shortens/reorders a frequency
   suffix, changes a tolerance, or invents a fact.
8. `minimum_validation_classification` and `primary_reason_code` exactly equal
   the outcome classification and single reason. Review cannot add warnings,
   secondary reasons, scientific recommendations, or an alternative
   classification.
9. A non-`VALIDATED_MINIMUM` outcome accepts no ScientificAcceptance IDs and
   projects only `INELIGIBLE`. A `VALIDATED_MINIMUM` with an empty explicit set
   projects `ELIGIBLE_UNACCEPTED`; with one or more exact acceptances for that
   outcome it projects `ACCEPTED`.
10. Acceptance IDs are explicit, finite, distinct, and sorted lexically only
    for deterministic projection. Duplicate, missing, wrong-outcome, stale, or
    conflicting acceptance evidence fails. Multiple valid acceptances remain
    separate complete mappings; no latest/current/preferred reviewer is
    inferred.
11. Exact unchanged source records and explicit acceptance set produce the
    same complete bundle, UUIDv5 identity, and JSON text across supported
    Python minors and caller mapping order.
12. Schema version, the exact Review namespace/domain in `boundary-spec.md`,
    and the frozen tagged canonical encoding are source-controlled and not
    caller-selectable. Boolean/integer distinction, lexical mapping-key order,
    sequence order, non-finite rejection, cycle rejection, and complete-payload
    identity are adversarially fixed.
13. Any projected source record, selected evidence, classification, primary
    reason, acceptance mapping, or acceptance-state change changes bundle
    identity. A forged/stale ID fails closed before rendering.
14. JSON rendering recomputes identity and emits exactly the complete public
    payload with the frozen JSON options and one final LF. Two renders of the
    same bundle are byte-identical and contain no hidden field, timestamp,
    local path, current-state query result, or free-form scientific inference.
15. A bundle for `INCOMPLETE`, `UNSUPPORTED`, or `NOT_MINIMUM` remains a legal
    factual review projection when its exact upstream records close; the
    renderer does not conceal the classification/reason or turn it into an
    accepted result.
16. Projection and rendering cause zero Core/Result/ScientificValidation
    mutation, zero Review persistence, zero filesystem write/read, zero
    transport/scheduler/Gaussian/viewer call, and zero retry, recovery,
    acceptance, or submission authority.
17. The selected geometry mapping retains exact Result source spans, ordered
    atoms, atomic numbers, units, and coordinates. Review does not infer bonds,
    element identity, connectivity, orientation preference, or calculation
    readiness.
18. Existing legacy review/report artifacts, hashes, paths,
    `calculation_ready`, approval decisions, and viewer manifests are never
    imported as Review authority. A narrow reuse report must retain the exact
    PORT/EXTRACT/WRAP/REWRITE/DROP/DEFER disposition and a concrete reason for
    REWRITE.
19. GaussView/external-viewer file generation, inferred bonds, SSH transfer,
    UI load probing, and GUI/rich report work remain deferred. A future wrapper
    may consume only the explicit selected geometry under a separate gate and
    cannot alter the bundle or create authority.
20. ScientificValidation public shape may inform this contract, but no Review
    product code, substitute record, local stub, or unmerged-worktree
    dependency is allowed before ScientificValidation implementation is
    integrated. `V30-VAL-REVIEW-01` and Review implementation require separate
    Owner Gates.

The projected-record key assertions are exact and set-based:

1. InputBinding projection keys equal exactly the 11-key set
   `schema_version`, `observation_id`, `attempt_id`, `calculation_plan_id`,
   `calculation_plan_revision`, `prepared_input_binding_id`,
   `execution_snapshot_id`, `input_format`, `logical_name`, `sha256`, and
   `size_bytes`.
2. OutputEnvelope projection keys equal exactly the 12-key set
   `schema_version`, `observation_id`, `attempt_id`,
   `input_binding_observation_id`, `execution_snapshot_id`,
   `capture_source_id`, `capture_sequence`, `capture_status`,
   `capture_completeness`, `artifacts`, `capture_manifest_sha256`, and
   `captured_at_utc`.
3. Every OutputArtifact projection keys equal exactly `artifact_kind`,
   `logical_name`, `sha256`, and `size_bytes`.
4. ParseOutcome projection keys equal exactly the 10-key set
   `schema_version`, `result_id`, `attempt_id`, `envelope_observation_id`,
   `parser_name`, `parser_version`, `result_kind`, `parse_status`, `facts`, and
   `diagnostics`.

No projected mapping may omit or add a key. Independent adversarial review and
future contract tests must additionally prove all of the following:

1. InputBinding `payload()` omitting `observation_id` cannot cause the
   projection to omit it.
2. OutputEnvelope `payload()` omitting `observation_id` cannot cause the
   projection to omit it.
3. ParseOutcome `payload()` omitting `result_id` cannot cause the projection to
   omit it.
4. A forged or replaced derived authority ID is rejected rather than copied.
5. The same exact typed record always yields a byte-equivalent projected
   mapping.
6. Mapping insertion order cannot change ReviewBundle identity.
7. Enum `repr` or member name cannot replace the exact public enum value.
8. Artifact path, mtime, local source path, or currentness cannot enter the
   projection.
9. Raw Gaussian output or artifact bytes cannot enter the ParseOutcome
   projection.
10. ReviewBundle identity and deterministic rendering consume exactly the same
    projected semantic mappings, including all three derived public authority
    IDs.

Focused future tests must include exact replay under reordered mappings,
every cross-splice axis in condition 5, mismatched ExecutionSnapshot IDs,
incomplete/unsupported/not-minimum bundles, all three acceptance states,
multiple explicit acceptances, duplicate/wrong-outcome acceptance rejection,
geometry/frequency byte-semantic preservation, forged bundle identity,
deterministic JSON, absence of raw-file/parser/viewer imports, and zero-effect
probes. No test may open a Gaussian log, contact SSH/RTwin/PBS/GaussView, or
create authority outside the exact upstream records.

## V30-WF-CONTRACT-01: Minimal Deterministic Workflow

**Status: CONTRACT FROZEN; IMPLEMENTATION NOT AUTHORIZED.** The following are
the exact acceptance conditions for V30-4. They grant no selector mutation,
Workflow implementation, Core change, Execution effect, `V30-EXEC-02`, or live
authority:

1. `auto_g16.workflow` is the sole public Workflow package and
   `tests/v3/workflow/` is its focused test package. Core, Approval, Execution,
   and Result never import Workflow.
2. The public inventory is exactly `Node`, `Edge`, `Map`, `Condition`,
   `HumanGate`, `WorkflowDefinition`, `WorkflowEvaluationInput`,
   `ConditionDecision`, `HumanGateDecision`, `WorkflowRunView`,
   `SQLiteWorkflowStore`, `record_workflow_definition`,
   `validate_workflow_definition`,
   `record_condition_decision`, `record_human_gate_decision`, and
   `replay_workflow`. Store lifecycle is exactly `create_new`, `open_existing`,
   and `close`; raw SQL/rows are private. Public functions accept only the
   exact store/Core/definition/evaluation/decision inputs frozen in the
   boundary and no effect adapter or callback.
3. `Node.node_id`, `Edge.edge_id`, `Map.map_id`, `Condition.condition_id`, and
   `HumanGate.human_gate_id` are non-empty local canonical identifiers scoped
   to one exact WorkflowDefinition, immutable inside it, and unique within
   their component namespaces; all intra-definition references use them. They
   are not complete-payload UUIDv5 identities and alone grant no
   cross-definition identity, persistence equivalence, authority, or effect.
   `WorkflowDefinition.workflow_definition_id` is schema-versioned,
   domain-separated UUIDv5 over the complete canonical definition payload,
   including every local ID and every component's complete semantics; reusing
   a local ID with changed semantics changes the definition identity.
   `ConditionDecision` and `HumanGateDecision` have separate domain-separated
   deterministic UUIDv5 identities binding the exact WorkflowDefinition ID,
   frozen Core/run identities, referenced local component ID, and complete
   decision payload. Exact authority-record replay is idempotent and the same
   authority identity with different content conflicts. No circular component
   identity computation is permitted: Edge-to-Condition and
   Condition-to-Edge IDs are ordinary intra-definition references inside the
   single definition payload. `WorkflowEvaluationInput` and the derived
   `WorkflowRunView` remain canonical value records without independent
   authority IDs and replay to byte-equivalent semantic values.
4. A definition is finite, non-empty, deeply immutable, serializable, and
   binds one exact existing Core WorkflowRun. Every Node binds one exact Task
   in that run and one exact existing CalculationPlan ID and positive revision
   for that Task.
5. Duplicate, missing, self, cross-run, cross-Task, stale-plan, unknown-role,
   ambiguous-producer, or orphan references fail closed. No new Core list,
   current-plan, or enumeration API is used or added.
6. The union of unconditional edges, every possible conditional edge, and
   every Map item's source-to-target dependency is acyclic. Map-only and mixed
   Edge/Map cycles fail closed. Stable lexical tie-breaking gives one
   deterministic topological order and readiness projection independent of
   input collection order.
7. A Map contains a finite non-empty set of unique explicit item keys and maps
   only to predeclared Nodes and input roles. Every item participates in the
   graph dependency, topological order, and readiness rules in condition 6. It
   cannot dynamically create, discover, or execute a Task, Node, callback,
   command, or program.
8. A Condition uses only the closed `attempt_state_in` predicate over an exact
   supplied source Attempt and a non-empty subset of `SUCCEEDED`, `FAILED`, and
   `NOT_SUBMITTED`. `always` Edges have no Condition; every conditional Edge is
   listed exactly once in the matching Condition and branch. True and false
   tuples are canonical and disjoint; mismatch, overlap, omission, duplicate,
   or cross-Condition membership fails closed.
9. Condition recording rejects missing, running, `UNKNOWN`, stale,
   cross-definition, cross-run, cross-node, cross-Task, or mismatched-state
   evidence without persisting a branch decision. The selected tuple is the
   complete canonical true tuple when the exact terminal state is expected and
   the complete canonical false tuple otherwise; caller-selected subsets,
   supersets, reordering, or cross-splicing fail closed.
10. A HumanGate decision binds the exact definition, run, and gate plus the
    explicit reviewer and evidence. HumanGate target sets are globally
    disjoint. For an already active target, missing means pending, rejected
    means blocked, and approved removes only that gate filter; a decision for
    an inactive target never activates it. Exact replay is idempotent; overlap,
    conflict, or cross-gate reuse fails closed and survives durable reopen.
    There is at most one decision for an exact definition/gate authority key.
11. HumanGate approval changes orchestration readiness only. It never creates
    Scientific Approval, Batch Submit Approval, Exact Operational
    Confirmation, scientific acceptance, a Core claim, or an external effect.
12. Workflow-owned SQLite schema version 1 stores immutable definitions and
    append-only typed decisions independently of Core and Approval stores.
    Fresh schema, exact replay, same-ID conflict, closed decoding, deterministic
    order, durable reopen, no implicit migration, and no update/delete behavior
    are tested. Create-new rejects an existing target; reopen rejects missing,
    wrong-version, malformed, extra, or conflicting state and performs no
    repair or initialization. Competing Condition decisions for one exact
    definition/condition/Attempt key also fail closed.
13. `WorkflowRunView` is always recomputed from the exact definition,
    decisions, explicit node-to-Attempt mapping, and public Core records. The
    same reopened inputs yield the same view; a stored mutable view cannot
    override those authorities.
14. Every supplied Attempt exists and belongs to the exact Node Task. Missing
    bindings remain explicit; Workflow neither enumerates nor chooses Attempts.
    Active roots and reachability are derived only from the combined graph and
    selected conditional Edges; neither an Attempt binding nor HumanGate can
    activate an inactive Node. A ready Node is only a proposal and creates no
    root Attempt.
15. Completed branch and HumanGate decisions survive reopen and cannot be
    spliced across definitions, runs, nodes, conditions, gates, Tasks, or
    Attempts. Map expansion and active-path projection are deterministic.
16. An active no-Attempt Node is ready only when all active always/Map
    predecessors are `SUCCEEDED`, selected conditional predecessors have exact
    terminal decisions, every input role has one active producer, and its gate
    is approved. Missing decisions are pending; rejection, failed always/Map
    predecessors, producer gaps, and `UNKNOWN` block. A run becomes
    orchestration-complete only when every active Node has an
    exact terminal Core outcome and all required decisions close. Completion
    does not imply execution success, valid chemistry, parsed Result maturity,
    or scientific acceptance. `pending`, `active`, `blocked`, and `completed`
    outcomes are deterministically derived rather than caller-selected.
17. `UNKNOWN` blocks the affected path and creates no retry, replacement,
    child, approval, confirmation, submission, or effect authority. Workflow
    never silently creates or adopts a recovery child.
18. Node readiness, Map, ConditionDecision, HumanGateDecision, and complete
    Workflow replay each produce zero Core transitions, workspace writes,
    adapter calls, transport, scheduler, PBS, Gaussian, cancellation, cleanup,
    or deletion.
19. The later Controller still needs current Scientific Approval, exact Batch
    membership, exact Operational Confirmation, and explicit Core `WINNER`
    before an effect. `REPLAY` and every non-winner path make zero effect calls.
20. Focused adversarial tests cover identity drift, Edge-only, Map-only, and
    mixed Edge/Map cycles, deterministic order and Map-aware readiness, role
    and mapping closure, Edge/Condition branch mismatch, true/false overlap,
    subset selection, terminal branch replay, overlapping gates,
    approved-plus-missing/rejected gates, inactive-target approval, store
    create/reopen closure, durable reopen, cross-splicing, `UNKNOWN`,
    zero-effect behavior, absence of
    callback/shell/eval surfaces, and byte-identical Core/Approval/Execution/
    Result public contracts.

V30-WF-CONTRACT-01 stops after independent contract review and repository
publication. V30-4 implementation remains blocked until separate Workflow
validation ownership is integrated and a new implementation Owner Gate opens.

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

## `V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01`

This resource-enactment contract is accepted only when all of the following
hold:

1. The exact identity-closed `ResolvedResourceRequest` inside the current
   `ExecutionSnapshot` is the sole authority for cores, integer MB, integer
   walltime seconds, and optional queue.
2. The private derived enactment repeats exact snapshot/resource IDs and all
   four values; changing any one rejects before qsub.
3. Current-profile canonical runtime content named exactly
   `pbs-resource-enactment-v1.json` has only the frozen schema and one closed
   dialect ID, and its bytes close through the resolved profile and snapshot.
4. Missing, unknown, malformed, aliased, or drifted dialect content rejects.
   No production dialect is inferred from generic scheduler knowledge.
5. `SUBMIT_QSUB_ONCE` carries the closed nested resource object and PBS
   basename only. Caller argv, argv fragments, shell, eval, format strings,
   executable selection, environment overrides, and fallback defaults are
   impossible or rejected.
   The payload keys are exactly `pbs_basename` and `resource_enactment`; the
   nested seven-key object, queue-null exception, binding equality rules, and
   958-byte canonical request vector replay exactly. The `/2` response has no
   new channel: its exact four-key envelope and one-key `{job_id}` result plus
   123-byte canonical response vector replay exactly.
6. The bootstrap selects only a source-controlled renderer and invokes the
   exact manifest-bound qsub executable with `shell=False`.
7. Null queue emits no selector; an explicit queue renders exactly or rejects.
   No queue substitution or inference occurs.
8. Walltime uses exact integer arithmetic without rounding; memory comes from
   `memory_mb`; cores come from `cores`. Gaussian `%mem` and `%nprocshared`
   neither authorize nor rewrite scheduler resources.
9. Caller PBS `#PBS -l`, `#PBS -q`, and equivalent resource directives remain
   rejected by `PbsTemplateBinding`.
10. Rendered qsub argv is deterministic only from dialect, exact resource
    request, and PBS basename and matches the exact reviewed vector. It is
    mechanical evidence, not persisted mutable authority.
11. Protocol `/2`, table `/2`, and fixed bootstrap-v2 source replace `/1` only
    for this closed request/table change. The seven operations, AGV3 framing,
    trust roots, bounded channels, physical bindings, and no-retry semantics
    remain unchanged.
    The exact bootstrap-v2 name, 15195 bytes, 201 LF, zero CR/NUL, and SHA-256
    `3f3653a8b13d4cb5a5f5ba6e9caa02c3049caf144af13fd4491674c1fc7eb2f3`
    replay exactly.
12. The only offline renderer is visibly synthetic, has a closed exact vector,
    and both live subprocess driver and bootstrap execution reject it before
    process/qsub creation. Its 114-byte descriptor and digest plus the
    1570-byte table-v2 vector and digest replay exactly. It cannot satisfy
    production live readiness.
13. Existing historical PBS artifacts are reuse evidence only. Until exact
    deployment evidence freezes a production dialect, the live path reports
    `NEEDS READ-ONLY DEPLOYMENT PREFLIGHT` and performs zero qsub.
14. Snapshot/resource/dialect splicing, queue/memory/time/core drift, request ID
    mismatch, and unexpected renderer tokens fail closed. `REPLAY` yields zero
    qsub; `UNKNOWN` never produces a second qsub.
15. No public Core/Approval/Workflow/Execution/Observe/Result/
    ScientificValidation/Review API or schema changes, and no planner,
    telemetry, retry, qdel, cleanup, deployment, OpenSSH, or live effect occurs.
16. Narrow reuse is recorded as PORT existing resource and no-shell primitives,
    EXTRACT only neutral deployment facts, WRAP the RTwin qsub mechanics,
    REWRITE the resource renderer because current v3 omits enactment and legacy
    governance is not authority, DROP legacy/free-form/default authority, and
    DEFER planning/telemetry/adaptive/multi-node policy.
17. Focused and affected evidence, exact negative vectors, static/diff/
    sensitive checks, and fresh independent contract and implementation review
    each close at `P0/P1/P2/P3 = 0/0/0/0` before integration.

## v3.0: Closed-Shell Minimum

A real closed-shell minimum completes:

`structure -> plan -> submit -> observe -> fetch -> parse -> ReviewBundle`

When this case meets its reviewed acceptance criteria, stop v3.0 feature
expansion.

## v3.1: Flexible-Molecule Ensemble

A real flexible molecule completes:

`xTB preopt -> CREST -> audit -> DFT -> Freq -> qRRHO -> ensemble`

When this case meets its reviewed acceptance criteria, stop v3.1 feature
expansion.

## v3.2a: Representative Reaction

A representative reaction completes:

`ReactionPlan -> TS search -> mode review -> bidirectional IRC -> endpoints -> barrier`

When this case meets its reviewed acceptance criteria, stop v3.2a feature
expansion.
