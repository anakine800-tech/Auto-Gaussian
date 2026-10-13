# Auto-G16 v3 boundary: result-attribution

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [V30-RESULT-01 Frozen Result Provenance Contract](result.md#v30-result-01-frozen-result-provenance-contract)
- [Composite internal-step Gaussian job successor](result.md#composite-internal-step-gaussian-job-successor)

<!-- Moved from docs/v3/boundary-spec.md:686-1301 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### Additive Gaussian job attribution contract

This additive Result contract does not change the existing
`GaussianLogParser` or any persisted `gaussian-log-facts` outcome. The legacy
public tuple remains exactly:

```text
parser_name    = auto-g16-v3-gaussian-log
parser_version = 1.0.0
result_kind    = gaussian-log-facts
```

Those outcomes remain readable historical program facts, but are insufficient
for ScientificValidation because their whole-log recognition cannot attribute
marker-like bytes to machine output rather than user-controlled echo. They are
never reinterpreted, migrated, backfilled, or rewritten as attributed facts.

The additive public parser is `GaussianJobParser`, with exact tuple:

```text
parser_name    = auto-g16-v3-gaussian-job
parser_version = 1.0.0
result_kind    = gaussian-job-facts
```

`auto_g16.result` adds only the public `GaussianJobParser` export for this
slice. It exposes the same pure parser shape as the existing parser:
`parse(envelope: OutputEnvelope, artifact_bytes: Mapping[str, bytes]) ->
ParseOutcome`, plus the three exact class-level tuple values above. Grammar,
token, span, and schema-validation helpers remain private; facts are carried by
the existing immutable `ParseOutcome` mapping rather than a second public
persistence record.

`GaussianJobParser` adds no Core record or identity primitive. `ParseOutcome`
keeps outer `schema_version = 1`, its exact public fields, and the existing
UUIDv5 identity over `(envelope_observation_id, parser_name, parser_version,
result_kind)`. Validation dispatches by that complete exact parser tuple. The
legacy tuple uses its unchanged closed facts validator; the new tuple uses the
closed `gaussian-job-facts` schema below. Missing, unknown, mixed, or
unsupported tuple members fail closed. Old and new outcomes may bind the same
envelope and coexist append-only with distinct Result identities.

#### Exact-byte grammar and capability boundary

The new parser is pure and deterministic over exact artifact bytes already
verified against one stored `OutputEnvelope`. Its source-controlled grammar ID
is `auto-g16-v3-gaussian-job-grammar/1`; that ID is a mandatory
`gaussian-job-facts` semantic field. A grammar change requires a new parser
version and produces a different Result identity. Locale, filesystem state,
mtime, line-ending conversion, lossy decoding, runtime probing, checkpoint
files, process state, and caller hints do not select grammar or facts.

The normative input domain is the original Gaussian-log artifact byte string
`B[0:L]`. The parser derives every offset before decoding or normalization.
Only LF (`0x0A`) and CRLF (`0x0D 0x0A`) terminate lines; CRLF is never rewritten
to LF. Scanning left to right produces records `(line_start, content_end,
line_end)`. For LF, `line_end = content_end + 1`; for CRLF,
`line_end = content_end + 2`. The final unterminated line has
`content_end = line_end = L`. Any other `0x0D` in a complete artifact is
`UNPARSEABLE` with `unparseable-line-terminator`. A blank line has content
matching exactly zero or more ASCII SPACE (`0x20`) or TAB (`0x09`) bytes.
No `.strip()`, Unicode whitespace, decoded-character offset, normalized-LF
offset, trimmed offset, or re-encoded offset participates.

Every normative source span is zero-based and half-open on `B`. A single-line
evidence span is `[anchor.line_start, anchor.line_end)`; a multi-line block is
`[first_grammar_line.line_start, final_grammar_line.line_end)`. Thus a span
includes the final line terminator when present, including both CRLF bytes. If
the final grammar line is the unterminated final line, its span ends at `L`.
No other source-span convention is legal.

All grammar patterns below are ASCII byte regular expressions applied with
full-match semantics (`\A...\Z`) to the raw line content, excluding its line
terminator. The notation is closed as follows:

```text
HT0  = [\x20\x09]*
HT1  = [\x20\x09]+
UINT = [0-9]+
INT  = [+-]?[0-9]+
NUM  = [+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd][+-]?[0-9]+)?
SYM  = [A-Za-z0-9?'+-]+
```

`NUM` therefore accepts leading signs, leading or trailing decimal points, and
`E/e/D/d` exponents, but not hexadecimal, comma, whitespace-internal, NaN,
Inf, or another `float()` extension. After ASCII conversion (`D/d` becomes
`E/e`), every number must be finite; overflow or a non-finite value is a
grammar failure. Integers are parsed in base ten and booleans are never
integers.

The exact line anchors are:

```text
BLANK               = \AHT0\Z
JOB_START           = \A\x20Entering Gaussian System, Link 0=g16\Z
OTHER_PROGRAM_START = \AHT1Entering Gaussian System, Link 0=g(?:03|09)HT0\Z
SYMBOLIC_START      = \AHT1Symbolic Z-matrix:HT0\Z
CHARGE_MULT         = \AHT1ChargeHT1=HT1INTHT1MultiplicityHT1=HT1[1-9][0-9]*HT0\Z
GRAD_BOUNDARY       = \AHT1(?:Grad){2,}HT0\Z
LINK1_LITERAL       = \AHT0--Link1--HT0\Z
INTERNAL_JOB_STEP   = \AHT1ProceedingHT1toHT1internalHT1jobHT1stepHT1numberHT1[2-9][0-9]*\.HT0\Z
UNSUPPORTED_ORIENTATION = \AHT1Z-Matrix orientation:HT0\Z
NORMAL_TERMINAL     = \AHT1Normal termination of Gaussian 16(?:HT1atHT1[\x20-\x7e]+)?\.?HT0\Z
ERROR_TERMINAL_A    = \AHT1ErrorHT1terminationHT1viaHT1Lnk1eHT1inHT1[\x21-\x7e]+HT1atHT1[\x20-\x7e]+\.HT0\Z
ERROR_TERMINAL_B    = \AHT1ErrorHT1terminationHT1requestHT1processedHT1byHT1linkHT1[0-9]+\.HT0\Z
```

`HT0`, `HT1`, `INT`, and the other named fragments are text substitutions in
these displayed patterns, not literal letters. `JOB_START` alone starts the
supported job. `OTHER_PROGRAM_START` is the closed unsupported-program case.
A genuine v1 multi-job boundary is `LINK1_LITERAL`, `INTERNAL_JOB_STEP`, or a
second `JOB_START` encountered only after `MACHINE_BODY` has been entered. The
same bytes in an input-echo state have zero effect. No naked `Entering Link 1`
substring is a job boundary.

The echo exit is also exact. `JOB_START` enters `INPUT_ECHO`; the unique ordered
sequence `SYMBOLIC_START`, then `CHARGE_MULT`, then at least one intervening
nonblank molecular-specification line, then `GRAD_BOUNDARY` enters
`MACHINE_BODY`. Every byte from `JOB_START` through the full
`GRAD_BOUNDARY` line is echo/control context and emits no scientific-neutral
fact. A duplicate/out-of-order boundary anchor, a `GRAD_BOUNDARY` before the
complete sequence, or more than one possible echo exit is
`UNPARSEABLE`/`unparseable-echo-boundary`. Thus title, route, comment, or
molecular-specification lines equal to optimization, stationary, frequency,
termination, orientation, `LINK1_LITERAL`, or `JOB_START` are ignored while in
an echo state; a spoofed boundary can only make the grammar fail closed. In
this paragraph and the table below, *echo-boundary anchor* means exactly
`SYMBOLIC_START`, `CHARGE_MULT`, or `GRAD_BOUNDARY`; it does not include
`JOB_START`, `LINK1_LITERAL`, or `INTERNAL_JOB_STEP` while an echo state is
active.

The machine-output anchors are:

```text
SCF = \AHT1SCF Done:HT1E\([^\x0d\x0a()]+\)HT1=HT1NUMHT1A\.U\.(?:HT1afterHT1UINTHT1cycles)?HT0\Z

OPT_HEADER = \AHT1ItemHT1ValueHT1ThresholdHT1Converged\?HT0\Z
OPT_ROW_MAX_FORCE = \AHT1MaximumHT1ForceHT1NUMHT1NUMHT1(?:YES|NO)HT0\Z
OPT_ROW_RMS_FORCE = \AHT1RMSHT1ForceHT1NUMHT1NUMHT1(?:YES|NO)HT0\Z
OPT_ROW_MAX_DISP  = \AHT1MaximumHT1DisplacementHT1NUMHT1NUMHT1(?:YES|NO)HT0\Z
OPT_ROW_RMS_DISP  = \AHT1RMSHT1DisplacementHT1NUMHT1NUMHT1(?:YES|NO)HT0\Z
OPT_PREDICTED     = \AHT1PredictedHT1changeHT1inHT1Energy=HT0NUMHT0\Z
OPT_DONE          = \AHT1Optimization completed\.HT0\Z
STATIONARY        = \AHT1--HT1Stationary point found\.HT0\Z

FREQ_HEAD_1 = \AHT1Harmonic frequencies \(cm\*\*-1\), IR intensities \(KM/Mole\), Raman scatteringHT0\Z
FREQ_HEAD_2 = \AHT1activities \(A\*\*4/AMU\), depolarization ratios for plane and unpolarizedHT0\Z
FREQ_HEAD_3 = \AHT1incident light, reduced masses \(AMU\), force constants \(mDyne/A\),HT0\Z
FREQ_HEAD_4 = \AHT1and normal coordinates:HT0\Z
MODE_NUMBERS = \AHT1UINT(?:HT1UINT){0,2}HT0\Z
SYMMETRIES   = \AHT1SYM(?:HT1SYM){0,2}HT0\Z
FREQUENCIES  = \AHT1FrequenciesHT1--HT1NUM(?:HT1NUM){0,2}HT0\Z
RED_MASSES   = \AHT1Red\. massesHT1--HT1NUM(?:HT1NUM){0,2}HT0\Z
FORCE_CONSTS = \AHT1Frc constsHT1--HT1NUM(?:HT1NUM){0,2}HT0\Z
IR_INTEN     = \AHT1IR IntenHT1--HT1NUM(?:HT1NUM){0,2}HT0\Z

ORIENTATION = \AHT1(?:Input|Standard) orientation:HT0\Z
SEPARATOR   = \AHT1-{5,}HT0\Z
GEOM_HEAD_1 = \AHT1CenterHT1AtomicHT1AtomicHT1Coordinates \(Angstroms\)HT0\Z
GEOM_HEAD_2 = \AHT1NumberHT1NumberHT1TypeHT1XHT1YHT1ZHT0\Z
ATOM_ROW    = \AHT1UINTHT1UINTHT1INTHT1NUMHT1NUMHT1NUMHT0\Z

THERMO_ZERO_POINT = \AHT1Zero-point correction=HT0NUMHT1\(Hartree/Particle\)HT0\Z
THERMO_ENERGY     = \AHT1Thermal correction to Energy=HT0NUMHT0\Z
THERMO_ENTHALPY   = \AHT1Thermal correction to Enthalpy=HT0NUMHT0\Z
THERMO_GIBBS      = \AHT1Thermal correction to Gibbs Free Energy=HT0NUMHT0\Z
THERMO_SUM_ZPE    = \AHT1Sum of electronic and zero-point Energies=HT0NUMHT0\Z
THERMO_SUM_H      = \AHT1Sum of electronic and thermal Enthalpies=HT0NUMHT0\Z
THERMO_SUM_G      = \AHT1Sum of electronic and thermal Free Energies=HT0NUMHT0\Z
```

The table's phrase *unrelated line* is closed: it means a line that full-matches
none of the named patterns above and triggers none of the prefix rules below.
Only a state whose row explicitly says that unrelated lines stay may ignore
such a line. Prefix testing is on raw content bytes after the initial `HT1`,
not decoded or stripped text. Outside an already admitted child production,
the closed prefix families are:

| Raw literal prefix after `HT1` | Diagnostic ownership when its exact production does not match |
| --- | --- |
| `Normal termination` or `Error termination` | `unparseable-terminal` |
| `SCF Done:`, or any of the seven displayed thermochemistry labels through and including `=` | `unparseable-numeric-token` only when every fixed literal/separator and the one numeric field slot is structurally present and that slot fails `NUM`/finite conversion; otherwise `unparseable-malformed-prefix` |
| `Item`, `Maximum Force`, `RMS Force`, `Maximum Displacement`, `RMS Displacement`, `Predicted change in Energy=`, `Optimization completed`, or `-- Stationary point found` | `unparseable-malformed-prefix` |
| `Harmonic frequencies`, `activities`, `incident light`, `and normal coordinates:`, `Frequencies`, `Red. masses`, `Frc consts`, or `IR Inten` | `unparseable-malformed-prefix` |
| `Input orientation:`, `Standard orientation:`, `Z-Matrix orientation:`, `Center Atomic Atomic Coordinates`, or `Number Number Type X Y Z` | `unparseable-malformed-prefix` |

`unparseable-orphan-anchor` applies only to an exact full-match of an
otherwise valid named anchor in a state where that anchor is illegal. Thus an
exact substate-only optimization or stationary pattern seen directly in
`MACHINE_BODY` is an orphan; so is exact `FREQ_HEAD_2`, `FREQ_HEAD_3`,
`FREQ_HEAD_4`, `FREQUENCIES`, `RED_MASSES`, `FORCE_CONSTS`, or `IR_INTEN` in
that state. In an admitted optimization, frequency, or geometry child, another
exact named anchor that is illegal in the current child state is likewise the
child's state-legality failure with this orphan code. A merely similar or
malformed prefix is never an orphan.
Separator, mode-number, symmetry, and atom-row-shaped lines have no standalone
meaning in `MACHINE_BODY` and are unrelated there; after their owning child
state has begun, the child state decides them. Prefix-family rules apply only
in `MACHINE_BODY` and `FREQUENCY_BODY` (including a line reprocessed into
either state); child states instead apply their own structural productions.
Exact-anchor orphan ownership also applies inside those child states. Both are
disabled in `PREAMBLE`, `TERMINATED`, and throughout the three input-echo
states, where the applicable state row alone decides the line. This makes a
user-echoed malformed scientific label as non-evidentiary as a valid echoed
label.

The FSM and its failure behavior are normative. Named transitions within one
state must be pairwise disjoint. If two named patterns match the same line, or
an omitted transition would be needed, the complete capture is
`UNPARSEABLE`/`unparseable-ambiguous-transition`; there is no priority, best
match, nearest marker, or last useful block.

| State | Accepted pattern and next state | Evidence/span | Any other relevant transition |
| --- | --- | --- | --- |
| `PREAMBLE` | `JOB_START -> INPUT_ECHO`; `OTHER_PROGRAM_START -> UNSUPPORTED` | none | other lines stay; EOF is `unparseable-job-start` |
| `INPUT_ECHO` | first `SYMBOLIC_START -> INPUT_MOLECULE` | none | `CHARGE_MULT` or `GRAD_BOUNDARY` fails echo boundary; every other line stays and emits nothing |
| `INPUT_MOLECULE` | first `CHARGE_MULT -> INPUT_MOLECULE_BOUND` | none | `SYMBOLIC_START` or `GRAD_BOUNDARY` fails echo boundary; every other line stays |
| `INPUT_MOLECULE_BOUND` | after at least one nonblank intervening line, `GRAD_BOUNDARY -> MACHINE_BODY` | none | `SYMBOLIC_START` or `CHARGE_MULT`, or `GRAD_BOUNDARY` before a nonblank intervening line, fails echo boundary; every other line stays |
| `MACHINE_BODY` | `SCF` stays; `OPT_HEADER -> OPT_MAX_FORCE`; `FREQ_HEAD_1 -> FREQ_HEAD_2_STATE`; `ORIENTATION -> GEOM_SEP_1`; a thermo line stays; legal terminal -> `TERMINATED`; multi-job anchor -> `LINK1_BOUNDARY`; `OTHER_PROGRAM_START` or `UNSUPPORTED_ORIENTATION -> UNSUPPORTED` | SCF/thermo/terminal lines use full-line spans | the closed prefix/orphan rules above apply; a repeated thermochemistry key is `unparseable-duplicate-evidence`; any `SYMBOLIC_START`, `CHARGE_MULT`, or `GRAD_BOUNDARY` is `unparseable-echo-boundary`; unrelated lines stay |
| `OPT_MAX_FORCE` | `OPT_ROW_MAX_FORCE -> OPT_RMS_FORCE` | none yet | child production precedence below selects numeric-token only for a structurally valid row with an invalid numeric field; every other mismatch is `unparseable-optimization-block` |
| `OPT_RMS_FORCE` | `OPT_ROW_RMS_FORCE -> OPT_MAX_DISP` | none yet | same ownership rule |
| `OPT_MAX_DISP` | `OPT_ROW_MAX_DISP -> OPT_RMS_DISP` | none yet | same ownership rule |
| `OPT_RMS_DISP` | `OPT_ROW_RMS_DISP -> OPT_AFTER_ROWS` | none yet | same ownership rule |
| `OPT_AFTER_ROWS` | optional one `OPT_PREDICTED` stays; `OPT_DONE -> OPT_STATIONARY`; any other line returns to `MACHINE_BODY` and is reprocessed once | `OPT_DONE` full-line span only on completion path | duplicate predicted fails; a complete non-converged table emits no marker evidence |
| `OPT_STATIONARY` | `STATIONARY -> MACHINE_BODY` | `STATIONARY` full-line span | anything else fails block; neither naked marker is evidence |
| `FREQ_HEAD_2_STATE` | `FREQ_HEAD_2 -> FREQ_HEAD_3_STATE` | block begins at `FREQ_HEAD_1.line_start` | anything else is `unparseable-frequency-block` |
| `FREQ_HEAD_3_STATE` | `FREQ_HEAD_3 -> FREQ_HEAD_4_STATE` | none | same failure |
| `FREQ_HEAD_4_STATE` | `FREQ_HEAD_4 -> FREQUENCY_BODY_EMPTY` | none | same failure |
| `FREQUENCY_BODY_EMPTY` | blank lines stay; `MODE_NUMBERS -> FREQ_SYMMETRY` | none | every other line is `unparseable-frequency-block`; a recognized frequency section must contain a complete group |
| `FREQUENCY_BODY` | blank/unrelated displacement lines stay; `MODE_NUMBERS -> FREQ_SYMMETRY`; a new `FREQ_HEAD_1 -> FREQ_HEAD_2_STATE`; `SCF`, `OPT_HEADER`, `ORIENTATION`, each thermo line, each legal terminal, each multi-job anchor, `OTHER_PROGRAM_START`, and `UNSUPPORTED_ORIENTATION` apply exactly as in `MACHINE_BODY` | none | orphan `FREQUENCIES`, `RED_MASSES`, `FORCE_CONSTS`, or `IR_INTEN` fails; echo-boundary anchors fail as in `MACHINE_BODY` |
| `FREQ_SYMMETRY` | `SYMMETRIES` with same 1..3 cardinality -> `FREQ_VALUES` | none | a structurally wrong line is `unparseable-frequency-block` |
| `FREQ_VALUES` | `FREQUENCIES` with same cardinality -> `FREQ_RED_MASSES` | values retained | child production precedence below selects numeric-token only after valid prefix/separators/cardinality; every other mismatch is frequency-block |
| `FREQ_RED_MASSES` | `RED_MASSES` with same cardinality -> `FREQ_FORCE_CONSTS` | none | same ownership rule |
| `FREQ_FORCE_CONSTS` | `FORCE_CONSTS` with same cardinality -> `FREQ_IR_INTEN` | none | same ownership rule |
| `FREQ_IR_INTEN` | `IR_INTEN` with same cardinality -> `FREQUENCY_BODY` | frequency-block span is mode line through IR line | same ownership rule |
| `GEOM_SEP_1` | `SEPARATOR -> GEOM_HEAD_1_STATE` | block begins at orientation heading | anything else is `unparseable-geometry-block` |
| `GEOM_HEAD_1_STATE` | `GEOM_HEAD_1 -> GEOM_HEAD_2_STATE` | none | same failure |
| `GEOM_HEAD_2_STATE` | `GEOM_HEAD_2 -> GEOM_SEP_2` | none | same failure |
| `GEOM_SEP_2` | `SEPARATOR -> GEOM_ROWS` | none | same failure |
| `GEOM_ROWS` | first/next `ATOM_ROW` stays; `SEPARATOR` after at least one row -> `MACHINE_BODY` | complete geometry span is heading through closing separator | wrong row shape or valid-integer row constraint is `unparseable-geometry-row`; a structurally valid row with an invalid numeric field is numeric-token; malformed/missing closure or EOF is geometry-block |
| `TERMINATED` | `BLANK` stays; genuine multi-job anchor -> `LINK1_BOUNDARY`; `OTHER_PROGRAM_START -> UNSUPPORTED`; another legal terminal -> failure | none | second terminal is `unparseable-terminal`; any other line is `unparseable-trailing-content` |
| `LINK1_BOUNDARY` | terminal classification | none | always `UNSUPPORTED`/`unsupported-multiple-job` |

At EOF, `PREAMBLE` reports `unparseable-job-start`; any echo state reports
`unparseable-echo-boundary`; an optimization, frequency (including
`FREQUENCY_BODY_EMPTY`), or geometry substate
reports its corresponding block code; `MACHINE_BODY` or `FREQUENCY_BODY`
reports `unparseable-terminal`; and `TERMINATED` succeeds. A line with a
recognized numeric field label but a token outside `NUM`, or a converted
non-finite value, reports `unparseable-numeric-token`. A legal numeric token
count/cardinality mismatch instead reports the owning block code. A malformed
`Normal termination` or `Error termination` prefix in machine context reports
`unparseable-terminal`.

#### Primary diagnostic ownership and precedence

`gaussian-job-facts` v1 has one primary diagnostic, never a diagnostic set.
`PARSED` persists `diagnostics = ()`; every terminal `PARTIAL`, `UNSUPPORTED`,
or `UNPARSEABLE` outcome persists a one-item tuple containing its single closed
code. Parsing and child productions are strictly left-to-right fail-fast over
original bytes and stop as soon as the active normative production can prove
failure.
No later byte is semantically examined for a competing failure, no second code
is collected, and no parent production may translate an already-owned child
failure into a broader code.

Within an admitted production, ownership is evaluated in this exact order:

1. current FSM/state legality;
2. required structural line or row shape;
3. closed field designation and field count;
4. each designated numeric field in left-to-right byte order;
5. required block closure or completeness.

A later level is evaluated only after all earlier levels succeed. Entry through
`OPT_HEADER`, `FREQ_HEAD_1`, or `ORIENTATION` admits the corresponding child;
that child owns every subsequent failure until it either returns to
`MACHINE_BODY`/`FREQUENCY_BODY` or terminates parsing. An exact valid named
anchor in a state where it is illegal is owned immediately by
`unparseable-orphan-anchor`. A malformed lookalike cannot be an orphan. Outside
an admitted child, one of the closed raw-prefix families above is owned by
`unparseable-malformed-prefix`, except the separately frozen terminal and
structurally complete direct SCF/thermochemistry numeric cases.

For diagnostic classification only, a raw field token is the maximal nonempty
byte sequence matching `[^\x20\x09\x0d\x0a]+`; this does not widen any accepted
line grammar. An optimization row has valid shape only when its exact label,
two raw numeric-field slots, final `YES|NO`, HT separators, and field count are
present. A frequency value row has valid shape only when its exact label,
`HT1--HT1`, the already-required 1..3 field slots, HT separators, and exact
cardinality are present. A geometry atom row has valid shape only when it has
exactly six HT-separated raw field slots after initial `HT1`, in the frozen
center/atomic-number/atomic-type/X/Y/Z order. Once shape succeeds, an invalid
`UINT`/`INT`/`NUM` field or non-finite conversion is
`unparseable-numeric-token`; the enclosing block emits nothing else. If more
than one field is invalid, the field with the smallest token start owns the
failure; equal starts use the displayed field order. Wrong row field count,
missing or extra structural tokens, a noncontiguous but valid integer center,
or an out-of-range but valid integer atomic number is
`unparseable-geometry-row`, never numeric-token. Within `GEOM_ROWS`, a line
whose content after initial `HT1` begins with `-` is a closure candidate:
exact `SEPARATOR` closes only after at least one row, while any malformed
separator or a separator before the first row is
`unparseable-geometry-block`; it is never classified as an atom row.

Consequently, `Frequencies -- NaN` in the legally required `FREQ_VALUES` state
has valid prefix/separators/cardinality and is uniquely
`unparseable-numeric-token`. A wrong frequency prefix, separator, or field
count in that state is `unparseable-frequency-block`; valid numeric rows
followed by a missing required continuation or closure are also frequency-block.
A valid geometry opener followed by a wrong required header/separator is
`unparseable-geometry-block`; a six-field row containing `NaN` is numeric-token;
a five- or seven-field row is geometry-row; valid rows without a closing
separator are geometry-block. In an optimization child, a structurally valid
row with an invalid numeric slot is numeric-token, while a wrong row/marker
sequence is optimization-block. An exact `STATIONARY` in an illegal state is
orphan-anchor and cannot compete with an optimization code.

EOF is a failure of the currently active production. EOF in an optimization,
frequency, or geometry child is owned by its block code; EOF in an echo state
is echo-boundary; EOF in `PREAMBLE` is job-start; and EOF in `MACHINE_BODY` or
`FREQUENCY_BODY` is terminal. EOF never creates an orphan, row, or numeric
failure. An earlier malformed geometry row therefore terminates parsing before
any later malformed frequency token can have authority.

Thermochemistry cardinality is a local child check within its otherwise
unchanged direct machine-fact production. Every candidate that is legal in the
current FSM state runs this exact, non-reorderable pipeline:

```text
validate exact line structure
-> resolve the already-frozen canonical thermochemistry fact key
-> validate the current numeric token against NUM
-> convert the current value and require it to be finite
-> test that key against previously committed thermochemistry evidence
-> commit key/value/source span when unseen
```

Only a current line that has passed the first four steps is eligible for the
duplicate check. A structural failure owns its existing structural diagnostic;
an invalid or non-finite current token owns `unparseable-numeric-token` and its
exact token span, even when the same key was committed earlier. Such a line is
never inserted into the seen-key set, and the outcome is `UNPARSEABLE`. If the
current fully valid canonical key was already committed in this supported job,
`unparseable-duplicate-evidence` owns the failure before the current evidence
is committed, and the outcome is `UNPARSEABLE`. Equal and unequal repeated
values are equally duplicates;
identical evidence is not an idempotent replay inside one ParseOutcome.

The duplicate check is scoped only to successfully committed earlier
thermochemistry evidence in this one supported Gaussian job. Equality is the
exact canonical fact key produced by the already-frozen mapping, never raw
spelling, display label, value, whitespace, or span. It does not cross a job,
capture, parser outcome, Attempt, or repository record. The duplicate
conformance span is always the full current/second line
`[line_start,line_end)`: it includes its LF or CRLF terminator, or ends at
artifact length `L` when the current line is the final unterminated line. It
never points to the first occurrence, both occurrences, a token-only span, or
a zero-width position.

The conformance failure position is the lowest original-byte position where
that active production proves failure. A numeric failure owns its exact token
span; a row-shape failure or exact orphan owns the full offending line span; a
block/header failure owns the full offending structural line. At EOF, ordering
position is `L`, while the non-zero conformance span is the full final
successfully consumed grammar-bearing line under the existing half-open span
rule. If no grammar-bearing line has been consumed, the conformance span is the
explicit no-span value, never a zero-width interval. Matrix outcomes have the
explicit no-position/no-span value because grammar is not run. The v1
`diagnostics` payload remains a tuple of code strings and does not add a
persisted position/span field; these positions are nevertheless normative for
implementation conformance and first-failure selection.

The exact optimization source spans are the `OPT_DONE` and `STATIONARY` full
lines, but they become evidence only after the entire ordered convergence block
has matched. Each frequency block span starts at its `MODE_NUMBERS.line_start`
and ends at its `IR_INTEN.line_end`; mode numbers must be strictly increasing
and contiguous across groups. Each geometry span starts at
`ORIENTATION.line_start` and ends at the closing `SEPARATOR.line_end`.
The literal `Input orientation:` heading maps only to
`orientation_kind = input-orientation`; `Standard orientation:` maps only to
`orientation_kind = standard-orientation`. `ATOM_ROW` fields map left to right
to center, atomic number, atomic type, X, Y, and Z. Atomic type is parsed and
discarded as non-authority. A center sequence other than exactly `1..N` or an
atomic number outside `0..118` is `unparseable-geometry-row`. An integer or
coordinate token outside its closed `INT`/`UINT`/`NUM` grammar, or a converted
non-finite coordinate, is `unparseable-numeric-token` after row shape succeeds.
Recognized malformed or truncated blocks emit no partial block fact and make a
complete capture `UNPARSEABLE`.

One supported job span is exactly
`[JOB_START.line_start, terminal.line_end)`, including both line terminators
when present. A final unterminated terminal line ends at `L`. After the terminal
line only `BLANK` lines are legal; another job/multi-job anchor is
`UNSUPPORTED`, and any other byte content is `UNPARSEABLE`. A missing legal
terminal, two legal terminals, or terminal-like text outside `MACHINE_BODY`
cannot be accepted as one parsed job.

Artifact verification precedes status selection. A supplied artifact-name set,
type, size, or SHA mismatch raises `MalformedEnvelopeError` and is never
converted into a `ParseStatus`. After exact verification, artifact cardinality
is fixed:

| CaptureCompleteness | Gaussian-log artifact count | Result |
| --- | ---: | --- |
| `PARTIAL` | 0 | `PARTIAL`, empty facts, `capture-partial` |
| `PARTIAL` | 1 | `PARTIAL`, empty facts, `capture-partial` |
| `PARTIAL` | >1 | `PARTIAL`, empty facts, `capture-partial` |
| `COMPLETE` | 0 | `UNSUPPORTED`, empty facts, `unsupported-gaussian-log-cardinality` |
| `COMPLETE` | 1 | run the exact grammar above |
| `COMPLETE` | >1 | `UNSUPPORTED`, empty facts, `unsupported-gaussian-log-cardinality` |

For one complete Gaussian-log artifact, exactly one supported job with a legal
terminal and complete deterministic attribution is `PARSED`. A genuine Link1,
second job, `OTHER_PROGRAM_START`, or `UNSUPPORTED_ORIENTATION` is
`UNSUPPORTED`; these are the only deliberate version-1 capability-boundary
patterns. Every other unmatched structural claim is malformed or ambiguous.
Malformed, contradictory, incomplete, or ambiguous bytes are `UNPARSEABLE`. A complete
capture never produces `PARTIAL`; uncertainty is not capture incompleteness.
Only `PARSED` carries the closed facts payload.

`PARSED` outcomes persist an empty diagnostics tuple. Non-`PARSED` outcomes
persist exactly one diagnostic code and no prose. This table is the complete
source-controlled vocabulary and single-owner production map:

| Diagnostic code | Owning production | Entry precondition and exact failure | Forbidden competing codes |
| --- | --- | --- | --- |
| `capture-partial` | capture/cardinality matrix | verified envelope is `PARTIAL`, for 0, 1, or >1 Gaussian logs; grammar is not run | every grammar/unsupported code |
| `unsupported-gaussian-log-cardinality` | capture/cardinality matrix | verified complete envelope has 0 or >1 Gaussian logs; grammar is not run | every grammar code |
| `unsupported-program` | FSM capability boundary | exact `OTHER_PROGRAM_START` in a legal non-echo state | every unparseable/prefix code |
| `unsupported-multiple-job` | FSM capability boundary | exact genuine multi-job anchor in `MACHINE_BODY`, `FREQUENCY_BODY`, or `TERMINATED` | orphan, prefix, trailing, and all block codes |
| `unsupported-valid-gaussian-grammar` | FSM capability boundary | exact `UNSUPPORTED_ORIENTATION` in machine context | malformed-prefix, orphan, and geometry codes |
| `unparseable-line-terminator` | raw line tokenizer | first lone `0x0D` in a complete artifact | every FSM/child code |
| `unparseable-job-start` | `PREAMBLE` | EOF before exact `JOB_START` after all earlier bytes were legal preamble | all other EOF/anchor codes |
| `unparseable-echo-boundary` | active echo state | exact out-of-order/duplicate echo-boundary anchor, or EOF before echo exit | orphan, malformed-prefix, and all evidence codes |
| `unparseable-ambiguous-transition` | active FSM state | two named exact transitions match the same current line | either transition's specific code |
| `unparseable-orphan-anchor` | active non-echo machine-output or child FSM state | exact otherwise-valid named anchor occurs where that exact anchor is illegal | malformed-prefix and every parent/child structural/numeric code |
| `unparseable-malformed-prefix` | machine-context prefix dispatcher | closed grammar-bearing prefix resembles a production but neither matches an exact anchor nor has a complete direct numeric-line shape, before a child is admitted | orphan, all child block/row codes, and numeric-token unless the direct numeric-line shape is complete |
| `unparseable-duplicate-evidence` | thermochemistry cardinality check | current FSM state legally admits the exact thermochemistry production; current structure, canonical-key resolution, numeric grammar, and finite conversion all succeed; prior committed evidence with that exact key exists; accepting the current fully valid evidence would make cardinality greater than one; authority span is the full current duplicate line `[line_start,line_end)` | numeric-token, the thermochemistry structural diagnostic, orphan-anchor, and every generic block diagnostic |
| `unparseable-optimization-block` | admitted optimization child | required row/marker shape or sequence is wrong, duplicated, prematurely terminated, or incomplete at EOF | orphan and numeric-token after valid row shape |
| `unparseable-frequency-block` | admitted frequency child | required header/prefix/separator/cardinality/continuation/closure is wrong or missing, including EOF | orphan and numeric-token after valid value-row shape |
| `unparseable-geometry-block` | admitted geometry child except atom-row production | required table header/separator/closure is wrong or missing, including EOF | orphan, geometry-row, and numeric-token |
| `unparseable-geometry-row` | `GEOM_ROWS` atom-row production | row has wrong field shape/count, or valid integers violate center contiguity or atomic-number range | geometry-block and numeric-token |
| `unparseable-numeric-token` | admitted numeric-field production | structural shape, field designation, and cardinality succeeded, then the earliest designated token fails `UINT`/`INT`/`NUM` or finite conversion | malformed-prefix, orphan, block, and row codes |
| `unparseable-terminal` | required terminal production | malformed terminal in `MACHINE_BODY`/`FREQUENCY_BODY`, repeated legal terminal in `TERMINATED`, or EOF in `MACHINE_BODY`/`FREQUENCY_BODY` before a legal terminal | malformed-prefix, orphan, block, and trailing-content |
| `unparseable-trailing-content` | `TERMINATED` | first nonblank line after the one accepted terminal is neither a genuine multi-job nor supported-program boundary | terminal and all child codes |

The first owned failure stops parsing; table order is descriptive and is never
a ranking or tie-break mechanism. `OTHER_PROGRAM_START` therefore maps only to
`unsupported-program`, every genuine multi-job anchor only to
`unsupported-multiple-job`, and `UNSUPPORTED_ORIENTATION` only to
`unsupported-valid-gaussian-grammar`. Invalid source-span bindings are rejected
by `ResultProvenanceService` before append and on reopen; they do not create a
second parser diagnostic or a legal `ParseOutcome`. Human-readable explanation
may be emitted outside persisted semantics only.

Given the same exact envelope, artifact bytes, and parser tuple, two conforming
implementations must produce the same status, job span, evidence spans, facts,
source ordering, primary failure position/span (or the same matrix no-position),
singleton diagnostic code, payload, and Result identity.
Evidence collections sort by `start`, then `end`, then the closed kind order
`termination`, `optimization`, `stationary`, `scf`, `frequency`,
`thermochemistry`, `geometry`. Frequency and geometry collections otherwise
retain byte-source order. No set or implementation traversal order is a
serialization authority.

#### Closed attributed facts schema

For the new exact parser tuple, non-empty `facts` has
`facts_schema_version = 1` and exactly these top-level semantics:

```text
facts_schema_version
grammar_id
source_artifact
job_section
program_status
normal_termination_count
error_termination_count
termination_evidence
optimization_completed_marker
optimization_completed_evidence
stationary_point_marker
stationary_point_evidence
scf_calculation_count
scf_calculations
final_energy_hartree
frequency_count
frequency_parse_complete
imaginary_frequency_count
frequencies_cm-1
frequency_blocks
thermochemistry
geometry_blocks
```

The schema is closed recursively: missing keys, unknown keys, wrong scalar or
container types, booleans used as integers, non-finite numbers, invalid enum
values, inconsistent counts/aggregates, or version drift fail closed on
construction and reopen. `source_artifact` binds exactly the stored
`envelope_observation_id`, `artifact_kind = gaussian-log`, portable logical
name, lowercase SHA-256, and non-negative byte size. Exactly one such artifact
of kind `gaussian-log` is supported as the fact source. Other envelope
artifacts remain part of the exact supplied-byte set and are verified but do
not contribute facts. The parser verifies all supplied bytes against the
envelope before recognition.

`source_artifact` has exactly `envelope_observation_id`, `artifact_kind`,
`logical_name`, `sha256`, and `size_bytes`. Every `source_span` has exactly
those five binding fields plus `start` and `end`. A span is a zero-based
half-open byte interval `[start, end)` with integer
`0 <= start < end <= size_bytes`. `job_section` is one such full source span.
Each termination, optimization, stationary-point, SCF, frequency-block,
thermochemistry, and geometry-block item carries a source span equal in its
five binding fields to `source_artifact` and contained by `job_section`.
Repeated evidence is ordered by `(start, end)` and distinct block instances may
not overlap; only the intentional containment of evidence by `job_section` is
allowed. Cross-envelope, cross-artifact, out-of-range, reversed, duplicate,
unordered, or otherwise impossible overlap fails closed.

`ResultProvenanceService` validates these relationships both before append and
while reopening stored outcomes: the exact envelope exists for the same
Attempt, the named artifact tuple equals the stored envelope artifact, every
span satisfies the closed interval/containment/order rules, the complete
parser tuple dispatches to the correct schema, and the Result identity is
recomputed. Existing Core append semantics make exact replay idempotent and
make the same Result identity with any different payload or span a conflict.
The service does not reconstruct bytes from spans and spans grant no execution
or scientific authority.

Termination, optimization-completed, stationary-point, SCF, frequency, and
thermochemistry facts arise only from grammar-recognized machine-output
records inside the exact job section. A raw occurrence in title, route,
comment, input echo, molecular specification, or other non-machine-output
context is ignored. `termination_evidence` items have exactly `kind`
(`normal-termination` or `error-termination`) and `source_span`.
Optimization and stationary evidence are ordered tuples of source spans.
`scf_calculations` items have exactly `energy_hartree` and `source_span`.
`thermochemistry` is a closed mapping over the existing seven allowlisted
thermochemistry names; each present item has exactly `value_hartree` and
`source_span`. Aggregates are exact projections of their attributed evidence:
counts match item cardinality, booleans match empty/non-empty evidence,
`final_energy_hartree` is the last attributed SCF value or null, and all finite
numerical values preserve source order. `program_status` is derived only from
the one recognized terminal record. A `PARSED` job has exactly one normal or
error terminal item, never both; the corresponding count is one and the other
is zero. Missing, repeated, malformed, or structurally contradictory terminal
evidence makes a complete capture `UNPARSEABLE`.

Each `frequency_blocks` item has exactly `source_span` and
`frequencies_cm-1`, a non-empty ordered tuple of one to three finite values as
required by the version-1 grammar. The top-level frequency tuple is the ordered
concatenation of all blocks; count and imaginary count are derived exactly, and
`frequency_parse_complete` is true for every `PARSED` outcome. A recognized
empty group, invalid token, wrong block cardinality, truncation, overlap, or
mixed context makes the complete capture `UNPARSEABLE`; no token is silently
skipped. Result does not decide whether the frequency set proves a minimum.

`geometry_blocks` contains every complete recognized machine-emitted
orientation block in byte order, not merely the first, last, or most favorable
one. Each block has exactly:

```text
orientation_kind = input-orientation | standard-orientation
units             = angstrom
source_span
atoms
```

`atoms` is a non-empty ordered tuple. Centers are contiguous one-based
integers; each atom has exactly `center`, integer `atomic_number` in `0..118`,
and finite `x`, `y`, `z` Cartesian coordinates. `source_span` uses the exact
closed mapping above. Atomic number `0` is preserved
as an explicit dummy-center fact and is unsupported by downstream minimum
validation; Result does not silently remove or reinterpret it. If any
recognized orientation block is malformed, truncated, mixed, non-contiguous,
non-finite, or incomplete, a complete capture is `UNPARSEABLE`; the parser
never skips that block or falls back to another geometry. Result calls these
generic geometry blocks and never labels one an optimized geometry or a
minimum.

#### Narrow reuse adjudication

The reuse audit is limited to `auto_g16.result.GaussianLogParser`, the public
Result models/service and their adjacent tests, plus the legacy
`skills/auto-g16-rtwin-pbs/scripts/gaussian_log.py` grammar/token helpers and
their adjacent tests.

- **PORT:** the existing `OutputEnvelope` artifact verification,
  `ParseOutcome` outer schema version 1, deterministic Result UUIDv5 tuple,
  append-only Core Result persistence, exact replay/conflict behavior, and
  same-Attempt provenance resolution.
- **WRAP:** preserve `GaussianLogParser` v1 and its historical
  `gaussian-log-facts` validator unchanged as a separate public parser tuple;
  it is readable history, not attributed ScientificValidation evidence.
- **EXTRACT:** finite D/E numeric-token conversion, SCF/thermochemistry field
  conversion, frequency-token parsing, and orientation-row parsing only after
  the new state machine has established an exact machine-output context. Each
  extracted primitive needs new context-bound and malformed-token tests.
- **REWRITE:** job/echo/context recognition, job multiplicity detection,
  frequency-block assembly, all-geometry-block assembly, and byte-span
  attribution. Existing implementations scan a whole log or select a last
  orientation and therefore cannot safely distinguish user echo or preserve
  complete attributed evidence.
- **DROP:** whole-log substring counts, membership/rfind marker authority,
  unscoped line regexes, last-job/last-orientation selection, silent malformed
  block skipping, and any legacy minimum/TS classification in the new parser.
- **DEFER:** multi-job/Link1 selection, checkpoint-derived geometry, scientific
  minimum/TS/IRC classification, scientific acceptance, live recapture, and
  Gaussian reruns.

This additive contract changes no Core API/schema and reopens no Execution,
Approval, or Workflow contract. It authorizes no ScientificValidation
implementation, transport, PBS, Gaussian, deployment, retry, or live action.
