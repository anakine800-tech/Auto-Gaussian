# Auto-G16 native Gaussian banner parser addendum

Status: ACCEPTED for implementation and offline validation on 2026-09-28.
Owner accepted the reviewed SHA-256
`56c92c09ff43164cf0e9bbc65fb93a9611be2c91f584d89dd11ef51f33649642`
by explicitly instructing completion of steps 1–5. The implementation contract
below is unchanged; this annotation records acceptance.
Parent: V31-GAUSSIAN-RESULT-REFINEMENT-01, OWNER-GUIDED, non-BUS.
Base: main `0d40520097d50fe02d9f55bd0b0ba25201d92c7e`.
Worktree branch: `codex/successor-result-refinement`.
Owner requested completion of the real-output gap and handoff item 3 on
2026-09-28. This document narrows that request into the explicit versioned
parser contract required by the accepted parent's parser-preservation rule.
Implementation and offline validation proceed after this delta is accepted;
publication, installation and live execution are not included.

## Evidence and bounded outcome

The retained native Gaussian capture has an absolute executable pathname in
its `Entering Gaussian System, Link 0=` line. Parser 1.1.0 accepts only the
literal basename `g16`, so it reports `unparseable-job-start`.
A diagnostic-only, process-local anchor substitution recognizes the unchanged
entire captured log. It does not persist a Result or assert source/scientific
authority. The native source chain and source file invariance were already
verified separately. Raw captures and machine-specific paths stay outside Git.

Add a separately selected parser tuple:

```
parser_name    = auto-g16-v3-gaussian-job
parser_version = 1.2.0
result_kind    = gaussian-job-facts
grammar_id    = auto-g16-v3-gaussian-job-grammar/3
```

Keep facts schema version 1 and its exact grammar-2 field inventory, numeric
rules, diagnostics, source spans and termination evidence. This adds only
native banner recognition and its corresponding fail-closed guards. It does
not change chemistry or make the historical RHF capture a wB97XD result.

## Exact banner grammar and state behavior

Accept a complete line with exactly one leading ASCII space and literal
`Entering Gaussian System, Link 0=`, followed by either `g16` or an absolute
POSIX path whose final component is exactly `g16`. Each preceding component
is nonempty and contains only ASCII letters, digits, `_`, `-`, `.`, or `+`;
components `.` and `..` are forbidden. No trailing whitespace, repeated slash,
relative path, backslash, quoting, expansion, shell punctuation, NUL or other
control character is accepted. The LF/CRLF tokenizer and byte offsets remain
unchanged. This is syntactic output recognition; no path is opened, resolved
or treated as executable identity or permission.

The equivalent supported path/basename forms ending in `g03` or `g09` are
recognized as another program and produce existing `unsupported-program`.
Other malformed or unsupported banner-looking lines outside input echo fail
with existing `unsupported-valid-gaussian-grammar`, never silently skip ahead
to find a later acceptable banner. A banner-looking line has the whitespace
prefix and literal `Entering Gaussian System, Link 0=`; leading whitespace
other than the accepted one space does not make it valid.

Use the new recognition consistently in PREAMBLE, machine/frequency body,
terminal state and structural sub-block guards. A second external Gaussian
banner in machine body or after termination is `unsupported-multiple-job`.
Within a structured block, preserve the existing orphan/block precedence.
Input echo suppression stays unchanged: user-controlled banner text inside
INPUT_ECHO, INPUT_MOLECULE or INPUT_BOUND is not executable/job evidence.
Internal-step sequencing, error precedence, `--Link1--` rejection and all
grammar-2 terminal/geometry/frequency/thermochemistry checks stay intact.

Do not rewrite bytes, strip the pathname, split/reassemble logs, patch module
globals at runtime or select a grammar by content heuristics. Reuse the owning
FSM through an explicit private immutable grammar policy. Parser 1.1.0's
default class and behavior stay unchanged, including its old negative result
for the native banner. Existing 1.0.0/1.1.0 stored tuple meanings and IDs are
unchanged. The new entry point is private; public exports remain unchanged.

## Explicit successor selection and retained revisions

The private Result parse adapter and Conformer composition functions gain an
explicit `parser_version` keyword, accepting only exact strings `1.1.0` and
`1.2.0`, with default `1.1.0` for compatibility. Each selected member input may
carry that keyword. No latest-version fallback or automatic alternate parse.
The selected tuple is bound by the derived Result's existing payload and ID;
the authority already binds that Result ID/hash. Source Observation identity
does not change for identical original evidence.

Only the private successor Opt interpretation admits 1.2.0 under the existing
pure-Opt rules. Public V30 `validate_minimum`, outcome tuple support, Review
and legacy conformer/Freq consumers keep their previous behavior. No new
minimum acceptance, Freq execution, populations, thermochemistry or TS gate.
Result model validation recognizes grammar-3 with grammar-2's exact fact
shape, but this does not confer downstream scientific support.

Keep exactly one successor source/parsed pair per Attempt in each destination
revision. Replaying 1.2.0 into a revision containing a 1.1.0 Result fails before
publication; it never replaces, deletes, appends a second parser version,
automatically chooses another base, or treats the old row as current 1.2.0.
To retain a new version, the caller must explicitly select an already-existing
destination snapshot without a derived pair (or with only the exact source
Observation under the already accepted partial-pair rule) and a fresh revision
filename. Preserve all its rows and leave old revisions untouched. If no such
destination exists, stop; this work cannot manufacture execution history or
remove old derived rows to create a suitable destination.

An identical 1.2.0 replay is idempotent. A read must explicitly select the same
version as its stored pair, reopen original proof/capture, parse the full exact
bytes, and compare all facts, diagnostics, IDs and spans. A valid self-hash or
a caller-supplied parsed success remains insufficient.

## Implementation and acceptance

Allowed delta: Result parser/shared FSM and model tuple validation; private
successor Result/Conformer dispatch; private ScientificValidation pure-Opt
tuple interpretation; their focused tests and existing owning authority and
validation-routing documents. No Core schema, execution intent, Transport,
Q7 material/publisher, source installation, frontend or scheduler changes.

Required evidence:

1. Old 1.0.0/1.1.0 reopen and default parser compatibility; old native-banner
   negative behavior remains reproducible. Public inventory remains exact.
2. New basename and absolute-path cases; rejected whitespace, malformed path,
   unsupported program, echo injection, second-job, embedded block/child-job,
   truncation, mixed internal-step and terminal cases; exact LF/CRLF spans.
3. Explicit version selection, unknown version rejection, deterministic Result
   and authority identities, correct-hash forged-facts rejection, old-pair
   conflict, source-only recovery and new revision reopen. Zero wire calls and
   unchanged original source bytes; no automatic baseline selection.
4. Replay the unmodified retained real capture through its original source
   owner and the new parser. Bind its whole-log SHA-256 and assert full parse,
   terminal counts, optimization/stationary markers, final energy, geometry
   inventory and every source span. Keep neutral Result parsing separate from
   the wB97XD-specific member authority; RHF is not promoted into that method.
5. Run the new tuple's synthetic approved-method Opt chain to immutable Result
   revision and ConformerEnsemble, with fresh-process deterministic replay.
   Reuse old-version focused/affected evidence where bytes and semantics are
   unchanged. Exact GoodVibes differential qualification remains a separate
   unchanged release check, not waived or claimed by this parser work.

Before implementation, independent read-only contract review must close
blocking findings and Owner accepts this exact delta. After implementation,
run focused/affected validation and independent read-only review. Use the
existing four-cycle/30-active-minute ordinary repair budget for this newly
defined parser repair, counting related failures across turns; no automatic
budget reset, live retry or resubmission.
