# Auto-G16 v3 boundary: scientific-validation

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:1356-1825 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-MIN-VALIDATE-CONTRACT-01 Minimum Scientific Validation Contract

**Contract status: FROZEN / INTEGRATED; IMPLEMENTATION NOT AUTHORIZED.**
The future public package is `auto_g16.scientific_validation`, with focused
tests under `tests/v3/scientific_validation/`. It owns post-Result scientific
classification and human scientific acceptance only. It changes no Core or
Result API/schema, imports no Approval, Execution, Workflow, Transport, or
program adapter, and grants no implementation, selector, effect, retry, or live
authority.

### Public boundary and exact provenance

The public inventory is limited to:

```text
MinimumValidationClassification
MinimumValidationOutcome
ScientificAcceptance
SQLiteScientificValidationStore
validate_minimum
record_minimum_validation
record_scientific_acceptance
require_scientific_acceptance
ScientificValidationError
ScientificValidationConflictError
ScientificValidationPersistenceIntegrityError
```

`MinimumValidationClassification` is exactly `VALIDATED_MINIMUM`,
`NOT_MINIMUM`, `INCOMPLETE`, or `UNSUPPORTED`. Public records are immutable,
keyword-only, and deeply closed over canonical semantic values. No warning,
probability, partial-minimum, or caller-defined outcome exists.

### Exact public shape and identity constants

The source-controlled schema version is exactly `1`, validation policy ID is
exactly `auto-g16-v3-minimum-validation`, and validation policy version is
exactly `1.0.0`. These values are implicit and are not caller-selectable or
additional public exports.

The ScientificValidation UUID namespace root is exactly
`f4617d31-5b90-5c79-888a-9b9ccec5e612`. The only identity domains and their
derived namespaces are:

```text
minimum-validation-outcome  6b963167-a628-5135-ad33-a38383cbf137
scientific-acceptance        333f02d6-ee57-53e6-bd43-3e02a7046e85
```

Each domain namespace is derived exactly as:

```python
uuid5(
    SCIENTIFIC_VALIDATION_NAMESPACE,
    "auto_g16.scientific_validation/v1/" + domain,
)
```

Canonical semantic nodes are tagged by exact runtime type as follows; Boolean
and integer are distinct, and the integer case excludes Boolean values:

```text
None          ["null", null]
bool          ["boolean", value]
int           ["integer", value]
finite float  ["float", value]
str           ["string", value]
mapping       ["mapping", [[key, canonical(value)], ...]]
sequence      ["sequence", [canonical(item), ...]]
```

Mapping keys are strings sorted lexically; sequence order is preserved.
Unsupported types, non-finite floats, and container cycles fail closed.
Canonical bytes are exactly:

```python
json.dumps(
    canonical_node,
    ensure_ascii=False,
    allow_nan=False,
    separators=(",", ":"),
    sort_keys=False,
).encode("utf-8")
```

The UUIDv5 name is the UTF-8 text of that encoding applied to:

```python
{
    "schema_version": 1,
    "domain": domain,
    "authority": complete_record_authority_payload,
}
```

ScientificValidation extracts this reviewed algorithm into its own private
implementation. It does not import Workflow, Core private encoding, or private
identity helpers, and it never substitutes `repr`, `pickle`, `hash`, ordinary
unsorted dictionary JSON, or platform-dependent serialization.

`MinimumValidationOutcome` is exactly
`@dataclass(frozen=True, slots=True, kw_only=True, init=False)` with these and
only these public fields:

```python
schema_version: int
minimum_validation_outcome_id: str  # init=False; deterministic UUIDv5
validation_policy_id: str
validation_policy_version: str
calculation_plan_id: str
calculation_plan_revision: int
attempt_id: str
input_binding_observation_id: str
envelope_observation_id: str
parse_result_id: str
parser_name: str
parser_version: str
result_kind: str
source_artifact: Mapping[str, object] | None
job_section: Mapping[str, object] | None
accepted_optimization_span: Mapping[str, object] | None
accepted_stationary_span: Mapping[str, object] | None
selected_geometry_block: Mapping[str, object] | None
selected_frequency_blocks: tuple[Mapping[str, object], ...]
selected_frequencies_cm1: tuple[float, ...]
classification: MinimumValidationClassification
reason_code: str
```

Schema and policy fields equal the fixed values above. Every ID is a non-empty
canonical string and `calculation_plan_revision` is a positive non-boolean
integer. Parser fields preserve the exact supplied `ParseOutcome` tuple.
Populated mappings and sequences are deeply immutable canonical semantic
copies of persisted Result facts, never bytes or reparsed evidence. When
evidence is unavailable at the first-applicable classification stage, an
optional mapping is `None` and each selected-frequency tuple is empty; no
placeholder mapping is invented. Populated `selected_frequencies_cm1` is
exactly the ordered concatenation of all populated
`selected_frequency_blocks`. A populated geometry block preserves its complete
Result-owned orientation kind, units, source span, and atoms.

`minimum_validation_outcome_id` binds every field above except itself, using
`classification.value` in the authority payload. Exact replay has the same ID
and record; any authority-field change creates a new ID; same ID with different
payload raises `ScientificValidationConflictError`.

`ScientificAcceptance` is exactly
`@dataclass(frozen=True, slots=True, kw_only=True, init=False)` with these and
only these public fields:

```python
schema_version: int
scientific_acceptance_id: str  # init=False; deterministic UUIDv5
minimum_validation_outcome_id: str
validation_policy_id: str
validation_policy_version: str
calculation_plan_id: str
calculation_plan_revision: int
attempt_id: str
parse_result_id: str
classification: MinimumValidationClassification
reviewer_id: str
review_evidence: Mapping[str, object]
```

All expanded outcome-binding fields exactly equal the persisted referenced
outcome, whose classification must be `VALIDATED_MINIMUM`. `reviewer_id` is a
non-empty canonical string. `review_evidence` is a non-empty deeply immutable
mapping whose nested values are limited to `None`, exact booleans, exact
integers, finite floats, strings, mappings with non-empty string keys, and
finite sequences of those values. Bytes, paths, datetimes, callables,
non-finite floats, cycles, and arbitrary objects fail closed. Reviewer identity
and review evidence participate in acceptance identity, so multiple explicit
acceptances for one outcome are legal and no current/latest pointer exists.

The exact public service signatures are:

```python
validate_minimum(
    core_store: SQLiteRuntimeStore,
    input_binding: InputBinding,
    envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
) -> MinimumValidationOutcome

record_minimum_validation(
    store: SQLiteScientificValidationStore,
    outcome: MinimumValidationOutcome,
) -> MinimumValidationOutcome

record_scientific_acceptance(
    store: SQLiteScientificValidationStore,
    *,
    minimum_validation_outcome_id: str,
    reviewer_id: str,
    review_evidence: Mapping[str, object],
) -> ScientificAcceptance

require_scientific_acceptance(
    store: SQLiteScientificValidationStore,
    *,
    minimum_validation_outcome_id: str,
    scientific_acceptance_id: str,
) -> tuple[MinimumValidationOutcome, ScientificAcceptance]
```

The validator accepts no policy argument and is pure except for read-only Core
lookups that close CalculationPlan and Attempt relationships.
`record_minimum_validation` appends the supplied exact outcome and returns the
typed replay. `record_scientific_acceptance` loads the exact persisted outcome,
requires `VALIDATED_MINIMUM`, derives and appends the expanded acceptance, and
returns it. `require_scientific_acceptance` loads both exact IDs, replays all
expanded bindings, and returns the typed pair; absence, mismatch, malformed
content, or ineligibility fails closed. None of these operations chooses a
latest acceptance.

The exact public store signatures are:

```python
SQLiteScientificValidationStore.create_new(
    path: str | Path,
) -> SQLiteScientificValidationStore

SQLiteScientificValidationStore.open_existing(
    path: str | Path,
) -> SQLiteScientificValidationStore

close() -> None
load_minimum_validation(outcome_id: str) -> MinimumValidationOutcome
load_scientific_acceptance(acceptance_id: str) -> ScientificAcceptance
minimum_validations_for_attempt(
    attempt_id: str,
) -> tuple[MinimumValidationOutcome, ...]
acceptances_for_outcome(
    outcome_id: str,
) -> tuple[ScientificAcceptance, ...]
```

The store exposes no raw SQL, connection, cursor, update, delete, migration,
or current/latest pointer. `ScientificValidationError` inherits `ValueError`
and owns semantic, provenance, and eligibility violations;
`ScientificValidationConflictError` and
`ScientificValidationPersistenceIntegrityError` inherit
`ScientificValidationError` and respectively own immutable identity replay
conflicts and database/schema/reopen/path/row integrity failures. There is no
fourth public error class.

Every `MinimumValidationOutcome` closes this one authority chain:

```text
exact CalculationPlan ID and positive revision
-> exact Attempt for that plan
-> exact same-Attempt InputBinding Observation
-> exact same-Attempt COMPLETE OutputEnvelope Observation
-> exact same-envelope ParseOutcome.result_id
-> exact source-controlled validation policy ID/version
-> MinimumValidationOutcome
```

The mandatory outcome semantics are `schema_version`,
`minimum_validation_outcome_id`, policy ID/version, plan ID/revision,
Attempt ID, InputBinding observation ID, envelope observation ID,
`parse_result_id`, exact parser tuple, exact source artifact identity and
selected evidence for a supported attributed tuple (or canonical explicit
absence for a non-parsed/unsupported outcome), accepted optimization and
stationary spans, selected geometry block, selected post-stationary frequency
blocks and values, classification, and exactly one closed primary
`reason_code`. There is no current/latest lookup, cross-capture, cross-envelope,
cross-Result, cross-parser, or cross-Attempt evidence splice.

The exact supported parser tuples are:

```text
parser_name    = auto-g16-v3-gaussian-job
parser_version = 1.0.0 | 1.1.0
result_kind    = gaussian-job-facts
```

Version `1.0.0` is bound only to grammar-1; version `1.1.0` is bound only to
grammar-2. Every other tuple remains unsupported.

The envelope must be complete and the ParseOutcome must bind that exact
envelope and same Attempt. Every relied-upon span must bind the exact
`source_artifact` mapping already closed by Result, including envelope ID,
artifact kind and logical name, SHA-256, size, and job-section bounds. The
validator consumes the persisted public records and facts only. It never opens
an artifact, accepts artifact bytes, scans a file, applies a Gaussian regex,
infers context from a substring, reparses output, or reconstructs a missing
fact. `AttemptResultView`, filesystem state, mtime, and a latest parser are not
authority.

Legacy `auto-g16-v3-gaussian-log` / `1.0.0` / `gaussian-log-facts`, any unknown
tuple, and a Result with `ParseStatus.UNSUPPORTED` classify `UNSUPPORTED`.
`PARTIAL` or `UNPARSEABLE`, an incomplete envelope, missing provenance, an
identity conflict, or missing required supported evidence classifies
`INCOMPLETE`. No migration, conversion, merge, backfill, or raw-output fallback
is permitted.

### Deterministic attributed-evidence selection

For a parsed grammar-1 tuple, ScientificValidation first requires exactly one
normal terminal fact, no error terminal fact, and `program_status =
normal-termination`. For grammar-2 it requires at least one normal terminal,
zero error terminals, terminal-evidence cardinality equal to the normal count,
and every terminal item normal. A context-attributed error termination is
always `INCOMPLETE`, never `NOT_MINIMUM` or `VALIDATED_MINIMUM`.

`optimization_completed_evidence` and `stationary_point_evidence` must be
non-empty tuples of equal cardinality. They pair only by the same tuple index.
For every index, the complete optimization span must precede its stationary
span; each pair must precede the next pair. Grammar-1 accepts the final pair.
Grammar-2 accepts the rightmost closed pair whose stationary span ends no later
than the first attributed frequency block. A missing, unequal, interleaved,
otherwise non-closing sequence, or grammar-2 frequency evidence preceding
every pair is `INCOMPLETE`; no marker boolean repairs it.

The final optimized geometry is the unique rightmost complete
`geometry_blocks` item in source-byte order whose `source_span.end` is less
than or equal to the accepted optimization-completed span's `start`. The block
and every atom are reused exactly as Result persisted them. A tie, overlap, or
absence is `INCOMPLETE`. No orientation preference, nearest-looking geometry,
filename, checkpoint, raw-output scan, coordinate reconstruction, or earlier
fallback participates.

The minimum-validation frequency evidence is the entire ordered suffix of
`frequency_blocks` whose `source_span.start` is greater than or equal to the
accepted stationary span's `end`. Every such block and every value is included
in byte order. A validator may not choose a favorable block or subset. Result's
closed grammar already requires ordered non-overlapping complete blocks,
continuous mode numbering, finite values, and an exact top-level projection;
ScientificValidation neither regroups analyses nor recomputes those rules.
Blocks before the accepted stationary evidence are not Hessian evidence for
this decision. The selected suffix and its spans are bound into the outcome.

These rules use only current `gaussian-job-facts` v1 fields and spans. They do
not add or reinterpret a Result fact. If a conforming implementation cannot
derive exactly these selections from those facts, it must stop rather than
read Gaussian output.

### V3.0 classification policy

Let `N` be the atom count in the selected geometry. V3.0 supports only the
ordinary nonlinear mode-count case and intentionally performs no geometric
linearity calculation. `N < 3` or any atom with atomic number `0` is
`UNSUPPORTED`. Otherwise the supported expected count is exactly `3*N - 6`.

The observed count is the number of values in the selected complete
post-stationary frequency-block suffix:

```text
observed < 3*N - 6  -> INCOMPLETE
observed = 3*N - 6  -> supported for minimum classification
observed > 3*N - 6  -> UNSUPPORTED
```

There is no linear-molecule angle, inertia, collinearity, or tolerance policy
in v3.0. Linear-molecule support may be introduced only by a later additive
policy version.

For otherwise complete supported evidence, every finite frequency `< 0.0` is
imaginary and every frequency `>= 0.0` is non-imaginary. There is no soft-mode,
rounding, low-frequency, or human-override tolerance:

```text
negative count = 0  -> VALIDATED_MINIMUM
negative count >= 1 -> NOT_MINIMUM
```

`-1e-12` is therefore imaginary and `0.0` is not. `NOT_MINIMUM` is used only
for complete supported evidence; it is never an error, incomplete, or
unsupported bucket.

Classification precedence is deterministic. Broken provenance, incomplete
capture, unparseable evidence, error termination, missing accepted marker pair,
missing eligible geometry, or too few selected modes is `INCOMPLETE`.
Structurally present evidence outside v3.0 support, including a legacy or
unsupported parser tuple, dummy center, `N < 3`, or too many modes, is
`UNSUPPORTED`. Only then do negative modes decide `NOT_MINIMUM` versus
`VALIDATED_MINIMUM`.

Each outcome carries exactly one primary reason code. Validation evaluates the
following ordered table top to bottom and stops at the first applicable row;
later conditions are not collected as secondary reasons:

| Order | First applicable condition | Classification | Exact reason code |
| ---: | --- | --- | --- |
| 1 | plan/Attempt/InputBinding/envelope/Result identity or same-source provenance cannot be closed | `INCOMPLETE` | `incomplete-provenance` |
| 2 | envelope is not complete | `INCOMPLETE` | `incomplete-capture` |
| 3 | parser tuple is legacy, unknown, or otherwise unsupported | `UNSUPPORTED` | `unsupported-result-tuple` |
| 4 | supported tuple has `ParseStatus.UNSUPPORTED` | `UNSUPPORTED` | `unsupported-parse-status` |
| 5 | supported tuple is partial, unparseable, or not parsed with closed facts | `INCOMPLETE` | `incomplete-parse` |
| 6 | attributed program status is error termination | `INCOMPLETE` | `incomplete-error-termination` |
| 7 | normal-terminal cardinality/status is missing or contradictory | `INCOMPLETE` | `incomplete-terminal-evidence` |
| 8 | optimization/stationary evidence does not form the required final ordered pair | `INCOMPLETE` | `incomplete-marker-pair` |
| 9 | no unique eligible final geometry exists | `INCOMPLETE` | `incomplete-final-geometry` |
| 10 | selected geometry has `N < 3` | `UNSUPPORTED` | `unsupported-atom-cardinality` |
| 11 | selected geometry contains atomic number `0` | `UNSUPPORTED` | `unsupported-dummy-center` |
| 12 | selected post-stationary mode count is below `3*N - 6` | `INCOMPLETE` | `incomplete-mode-count` |
| 13 | selected post-stationary mode count is above `3*N - 6` | `UNSUPPORTED` | `unsupported-mode-count` |
| 14 | one or more selected frequencies are `< 0.0` | `NOT_MINIMUM` | `negative-frequency` |
| 15 | every prior rule passes | `VALIDATED_MINIMUM` | `validated-minimum` |

The table is the complete reason-code vocabulary for policy v1. Exactly one
row owns every returned outcome; a tuple/set of multiple reasons, warning code,
exception string, presentation message, or caller-selected reason is invalid.
Thus simultaneous missing marker, geometry, and mode evidence is owned only by
`incomplete-marker-pair`, the first applicable row.

### Identity, acceptance, and persistence

`MinimumValidationOutcome` uses a source-controlled namespace and a
schema-versioned, domain-separated UUIDv5 over its complete canonical authority
payload, including expanded selected evidence, classification, and the one
primary reason code. Exact replay
has the same identity and payload. The same identity with different content is
a conflict. A changed Result, plan revision, policy version, selected fact, or
classification produces a new identity. Timestamps, serialization formatting,
temporary paths, and opaque digests never decide authority by themselves.

`ScientificAcceptance` is a separate immutable record containing its schema
version and domain-separated deterministic ID, the exact persisted
`minimum_validation_outcome_id`, expanded outcome identity/policy binding,
reviewer identity, and canonical review evidence. It may be created only for
an exact persisted `VALIDATED_MINIMUM`. No acceptance record exists for
`NOT_MINIMUM`, `INCOMPLETE`, or `UNSUPPORTED`; refusing acceptance creates no
promotion record. Acceptance never mutates Result, Attempt, CalculationPlan,
or the validation outcome and grants no effect authority.

`validate_minimum(core_store, input_binding, envelope, parse_outcome)` is pure
and non-persisting. It validates the exact public Core/Result chain and returns
one deterministic outcome without artifact bytes. `record_minimum_validation`
appends that exact outcome. `record_scientific_acceptance` derives and appends
an acceptance for an exact persisted validated outcome.
`require_scientific_acceptance` replays the exact pair or fails closed; all four
operations have zero Core transition and zero external effect.

`SQLiteScientificValidationStore` owns schema version 1 separately from Core
and Result. Its lifecycle is `create_new(path)`, `open_existing(path)`, and
`close()`. Its minimum reads are `load_minimum_validation(outcome_id)`,
`load_scientific_acceptance(acceptance_id)`,
`minimum_validations_for_attempt(attempt_id)`, and
`acceptances_for_outcome(outcome_id)`, with deterministic insertion order.
Rows are append-only; exact replay is idempotent; conflicting replay fails;
closed typed rows and unexpected schema objects are attested on reopen. There
is no migration, update, delete, current pointer, raw-SQL public surface, Core
table, or Result mutation. Fresh creation is no-overwrite, and reopen rejects
terminal symlink/non-regular/replacement identity drift without resolving away
the caller's terminal path.

### Reuse disposition and non-goals

- **PORT:** public immutable Core/Result records, exact Result identity and
  provenance closure, `GaussianJobParser` tuple dispatch, attributed source
  spans, closed geometry/frequency facts, append-only replay/conflict patterns,
  and local SQLite file-integrity patterns.
- **DROP:** every failed-candidate raw-byte scanner, one-section workaround,
  terminal-orientation parser, whole-log aggregate assumption, duplicated
  Gaussian grammar, favorable-block selection, empirical frequency tolerance,
  legacy minimum/receipt/owner/hash-currentness authority, and any attempt to
  repair or backfill Result evidence.
- **DEFER:** linear-molecule policy, TS/IRC/connectivity, conformer ensembles,
  qRRHO/thermochemistry policy, reaction barriers, excited/open-shell/metal
  policy, Observe, ReviewBundle, generic scientific plugins, and all live work.

This contract defines no implementation, selector ownership, transport,
execution, retry, recovery, submission, Gaussian run, or scientific acceptance
for a real artifact. `UNKNOWN` creates no retry or replacement authority. Any
need for a new Result fact/span, raw-output interpretation, upstream contract
change, or broader scientific policy is an Owner stop.
