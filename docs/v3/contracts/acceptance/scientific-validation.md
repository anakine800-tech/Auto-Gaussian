# Auto-G16 v3 acceptance: scientific-validation

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:502-654 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

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
3. Only `auto-g16-v3-gaussian-job` / (`1.0.0` grammar-1 or `1.1.0`
   grammar-2) / `gaussian-job-facts` may support minimum classification.
   Legacy `gaussian-log-facts`, unknown tuples, and a Result with
   `ParseStatus.UNSUPPORTED` are `UNSUPPORTED`, never converted, merged,
   backfilled, or reparsed.
4. The exact plan/revision -> Attempt -> same-Attempt InputBinding -> COMPLETE
   OutputEnvelope -> same-envelope ParseOutcome/result ID -> policy/version
   chain is replayed through public records. Latest/current lookup and evidence
   splicing across captures, envelopes, Results, parsers, or Attempts rejects.
5. A supported `PARSED` fact mapping must bind every relied-upon span to the
   exact Result source artifact, envelope, job section, logical name, kind,
   size, and SHA-256. Partial/unparseable evidence, malformed provenance, or a
   missing supported fact is `INCOMPLETE`.
6. Grammar-1 normal classification requires exactly one attributed normal
   terminal and no error terminal. Grammar-2 requires one or more ordered
   normal terminals, no error terminal, and exact count/evidence agreement.
   Attributed error termination is `INCOMPLETE`, never `NOT_MINIMUM` or
   `VALIDATED_MINIMUM`.
7. Optimization and stationary evidence tuples are non-empty and equal in
   length, pair by index, and close in strict source order. Grammar-1 accepts
   the final pair. Grammar-2 accepts the rightmost closed pair preceding the
   first attributed frequency block. Missing, unequal, interleaved, ambiguous,
   or wholly post-frequency pairing is `INCOMPLETE`.
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

<!-- Moved from docs/v3/acceptance.md:1521-1529 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## v3.0: Closed-Shell Minimum

A real closed-shell minimum completes:

`structure -> plan -> submit -> observe -> fetch -> parse -> ReviewBundle`

When this case meets its reviewed acceptance criteria, stop v3.0 feature
expansion.
