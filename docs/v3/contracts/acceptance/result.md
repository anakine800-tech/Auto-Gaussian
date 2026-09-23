# Auto-G16 v3 acceptance: result

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:180-501 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

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

## V30-A Gaussian Opt/Freq Composite Job Result Successor

**Status: OWNER AUTHORIZED IMPLEMENTATION.** The successor is accepted only
when all of the following hold without changing the public fact shape:

1. `GaussianJobParser` publishes exactly `auto-g16-v3-gaussian-job` / `1.1.0`
   / `gaussian-job-facts` and every parsed fact mapping binds grammar
   `auto-g16-v3-gaussian-job-grammar/2`.
2. Historical `1.0.0` / grammar-1 payloads construct, persist, reopen, and
   retain their original identity and exact-one-terminal semantics.
3. One external invocation with no internal step remains parsable under
   grammar-2. A second external start or exact `--Link1--` remains unsupported.
4. Internal steps start at 2 and are strictly contiguous. Starts at 3,
   duplicate 2, sequence 2-to-4, or continuation after error fail closed.
5. Each internal marker is preceded by a closed normal component. Multiple
   terminals without corresponding internal structure, an extra terminal
   inside a component, or a nonterminal final component is unparseable.
6. Repeated exact `GradGrad...` separators are accepted only at parser top
   level. A separator inside an unfinished optimization, frequency, geometry,
   or other child production fails with that production's closed diagnostic.
7. A successful two-component Opt/Freq fixture reports two ordered normal
   terminal spans, zero error terminals, one complete external `job_section`,
   exact optimization/stationary spans, exact geometry spans, and exact
   frequency blocks. Physical terminals are not collapsed.
8. Grammar-2 normal status requires every component terminal to be normal and
   the final component to be closed. Any error terminal produces overall error
   status and cannot be followed by a successful continuation.
9. ScientificValidation accepts both exact parser generations. Grammar-1
   retains exactly one normal terminal. Grammar-2 requires normal count at
   least one, zero errors, equal terminal-evidence cardinality, and every item
   normal.
10. For grammar-2, the accepted optimization/stationary pair is the rightmost
    closed pair preceding the first frequency block. The unique final geometry
    before that optimization and every frequency block after its stationary
    marker remain the sole attributed minimum evidence. A frequency block
    before every closed pair cannot validate a minimum.
11. Nonlinear `3*N-6`, atomic-number-zero handling, exact `< 0.0` negative
    threshold, four classifications, provenance closure, deterministic
    identities, persistence, and separate ScientificAcceptance remain
    unchanged.
12. The immutable 110346-byte V30-A capture with SHA-256
    `b2dd97287870c22d23934e60d835616492a6923256b40cebe41413d3f7e99a08`
    is parsed only as ordinary grammar-2 input, with no artifact-specific
    branch, fixed offset, molecule name, filename, or digest special case.
13. Exact-capture qualification is zero-network and produces `PARSED`, two
    normal terminals, zero error terminals, three frequencies
    `(2017.6012, 3611.7356, 3835.6281)`, and a three-atom selected geometry.
14. Focused and affected offline checks, independent P0/P1/P2/P3 review,
    required CI, CodeQL, merge identity, and exact-main replay all pass before
    the successor may terminalize the historical live Attempt.
15. No test or replay opens SSH, reads scheduler state, fetches, executes,
    allocates, stages, submits, retries, cancels, deletes, cleans, deploys, or
    creates another Attempt.
