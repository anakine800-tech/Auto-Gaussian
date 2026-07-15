# Auto-G16 calculation-artifact adapter contract

Status: first offline adapter slice. This contract grants no Gaussian, SSH,
PBS, server-directory, staging, retry, cancellation, cleanup, deployment, or
live-execution authority. The implementation is owned by
`auto-g16-reaction-workflow`; candidate, protocol, Gaussian-input, scheduler,
terminal-intake, and TS scientific semantics remain owned by their specialist
validators.

## Integrity and authority boundary

Every adapter artifact is immutable, refuses overwrite, and binds local
non-symlink inputs. JSON inputs are loaded strictly: duplicate keys,
non-finite numbers, unknown contract fields, malformed hashes, and source
drift are rejected. An artifact reference has exactly:

```json
{
  "path": "relative/or/absolute/path",
  "sha256": "exact-file-sha256",
  "size_bytes": 123,
  "schema": "schema/name-or-null",
  "payload_sha256": "owned-payload-sha256-or-null"
}
```

`sha256` and `size_bytes` bind the exact file bytes. `payload_sha256` binds the
canonical owned JSON payload when the referenced schema exposes one; it is
`null` for non-JSON artifacts such as XYZ and Gaussian input and for a JSON
schema with no adapter-recognized owned-payload field. A field that hashes a
different upstream object, such as terminal intake's template payload, is
never mislabeled as the referenced document's payload. Paths are lineage
locators, never authority to replace a bound file.

The adapter uses one fixed reference boundary so deterministic bytes do not
depend on the process working directory: a file below the repository root is
recorded relative to that root; a file outside it uses an explicit absolute
fallback because there is no honest common portable root. Callers that require
fully relocatable exchange must place the complete study package under the
repository/package root before finalization. Output paths themselves reject lexical `..` escape
and every existing symlink ancestor before creating a parent directory; an
explicit absolute output remains explicit rather than being silently rebased.
All source references likewise reject lexical parent traversal and any
symlinked path component. Derived output references must use the builder's
canonical repository-relative-or-explicit-absolute locator; an owner-relative
alias that happens to resolve to the same bytes is not an equivalent lineage
claim.

The public `validate` command does more than accept a well-formed, newly
rehashed document. It rechecks strict schema and owned-payload validity, every
referenced file's exact bytes, size, schema and payload, and deterministically
rebuilds target imports, input handoffs, energy lineages plus their records,
and attempt links from their bound source artifacts. Rehashed edits to derived
eligibility, identity, audit facts, energy projection, or preserved
classifications are rejected. A bare `gaussian-reviewed-energy-record/1` has
no source pointers of its own and is therefore refused by standalone
validation; validate its exact `gaussian-energy-lineage/1` sidecar instead.

All schemas in this slice require `calculation_ready: false` and
`no_submission_authorization: true`. Here, an exact offline input handoff means
only that the reviewed draft can be reproduced byte-for-byte. It does not mean
the repository's live calculation prerequisites have been met: the adapter
does not record an exact live approval, fresh server project, submission
decision, or executable DAG node. Consequently it must not set
`calculation_ready` to `true`.

The following gates remain independent and non-transitive:

1. candidate construction and promotion;
2. protocol-option selection;
3. exact input-draft review;
4. exact live approval;
5. execution status; and
6. scientific acceptance.

Approval at one gate never supplies or authorizes a later gate.

## Candidate ledger to target import

`gaussian-candidate-target-import/1` is an immutable exchange envelope, not a
calculation plan. It binds the reviewed asymmetric-catalysis study and full
candidate ledger, retains every specialist-valid ledger entry, and also
retains the ledger's excluded combinations as closed source-index,
canonical-JSON and source-record-hash envelopes without guessing the
specialist-owned exclusion shape. This includes unmaterialized,
logical-duplicate, materialized-unique, and geometry-duplicate entries; an
unsupported, blocked, or rejected materialized candidate remains represented
with its exact support/review state and blockers.

Each target has a stable
`asymmetric_candidate:<study_id>:<candidate_id>` `external_target_key`, the
source-entry hash and disposition, typed `artifact_roles`,
`dependency_external_keys`, exact source diagnostics, and factual adapter
checks in `readiness_facts`. Duplicate relationships use external keys rather
than an internal DAG identifier. Targets and artifact roles are emitted in
stable order.

`eligible_for_later_input_review` is true only for a
`materialized_unique` candidate that is
`supported_main_group_closed_shell`, is explicitly `promoted_offline`, binds
an exact local geometry, is a reviewed closed-shell singlet within the V1
element/wavefunction scope, has complete stereochemistry/clash reviews, and
has no unresolved candidate warnings. Each of these is a factual readiness
field with an explicit blocker when false. This is an
offline filter only. It is neither DAG readiness nor calculation readiness,
and it does not choose a protocol or authorize input construction.

## Reviewed candidate and protocol to exact input

Version 1 implements one deliberately narrow workflow kind:
`closed_shell_main_group_single_guess_ts_freq`. It supports a promoted,
closed-shell singlet, main-group asymmetric-catalysis candidate with one
explicit Cartesian XYZ geometry and one reviewed TS optimization plus harmonic
frequency task. The exact study, candidate, XYZ bytes, atom order, formula,
element counts, charge, multiplicity, protocol-options artifact, and explicit
protocol-selection artifact must all agree.

`gaussian-input-draft-review/1` is a separate exact review. It must enumerate
the bound sources and explicitly accept all input-bearing content:

- `%chk`, `%mem`, and `%nprocshared` Link 0 values;
- the complete one-line route;
- resource tier, memory, cores, and one-stage expectation;
- title;
- charge, multiplicity, atom identities, atom order, and element inventory;
- an explicitly empty trailing-section list; and
- the SHA-256 of the exact rendered input bytes.

The adapter does not derive a method, basis, solvent, TS algorithm, route, or
resource request from chemistry. It renders only the accepted review, checks
its resource facts against the exact selected protocol option, and delegates
the single-guess family audit to `auto-g16-ts-irc` and final Gaussian syntax,
resource, charge/spin, inventory, geometry-source, and hash audit to
`auto-g16-rtwin-pbs`.

Version 1 refuses metal or otherwise unsupported-element candidates,
open-shell or broken-symmetry cases, unresolved multireference cases, QST2,
QST3, IRC, `Geom=Check`, `Geom=AllCheck`, `Guess=Read`, Link1 input, ONIOM,
scan/ModRedundant input, general-basis or ECP trailing sections, old-checkpoint
geometry, multiple task stages, missing review, source drift, route/resource/
identity mismatch, and any non-empty trailing section. An unsupported case
must be extended under a new reviewed contract rather than coerced into V1.

Only after all prerequisites pass may the builder write the exact `.gjf` and
its required `<input-stem>.handoff.json` companion. The companion uses
`gaussian-candidate-input-handoff/1`, binds every source and the exact input,
records both specialist audits, and records the six gates separately. It still
has `calculation_ready: false` and `no_submission_authorization: true`; it must
not be treated as a staging or submission manifest.

## Specialist result to reviewed energy and lineage

The energy adapter consumes only existing specialist JSON with schema
`gaussian-ts-freq-result/1`; it never opens or parses a raw Gaussian log and
never reinterprets an imaginary mode, TS validity, IRC path, endpoint, or
specialist status. `gaussian-energy-review/1` binds the exact candidate and
parsed result and may bind an exact TS mode review and scientific decision as
a pair. When that pair is present, their parsed-result and review hashes must
close exactly.

The adapter calls the TS specialist's pure
`classify_ts_freq_result_facts` and `validate_mode_review_geometry` helpers.
The first replays parser-owned status and first-order-saddle/mode-review
eligibility from the termination and scientific facts; disagreement is
rejected, never rewritten. The second checks that mode-review displacement
coverage, positive contiguous indices, elements/atomic numbers, finite
coordinates and vectors, amplitude, atom pairs, and equilibrium/plus/minus
distance projections are exact arithmetic consequences of the parsed final
coordinates and sole imaginary mode. This is arithmetic consistency only:
intended-coordinate meaning and accepted/rejected/unclear remain specialist
and human scientific decisions.

Version 1 permits only the explicitly enumerated source field
`final_energy_hartree`, with unit `hartree`. If the review accepts that field,
the specialist value is finite, and the exact paired scientific-review
artifacts are present, the builder emits an `electronic_only`
`gaussian-reviewed-energy-record/1`; otherwise it emits `blocked` with no
invented electronic value. In both cases, `gaussian-energy-lineage/1` records
the exact sources, projected fields, omissions, and blockers.

Thermal Gibbs correction, temperature, standard state, low-frequency policy,
common reference, comparison free energy, relative barrier, selectivity, and
kinetic claims remain absent. `comparison_eligible` is always false. Missing
thermal or comparison evidence is a blocker, not permission to manufacture a
default or a comparable free energy. Specialist classifications are copied as
observed and are not upgraded by the adapter.

## Observation-only attempt linkage

`gaussian-sanitized-job-observation/1` removes live identifiers while binding
the exact source job-record hash and input hash. It must declare that `job_id`
and `remote_workdir` were redacted.

`gaussian-calculation-attempt-link/1` is an immutable observation sidecar. It
binds, by exact artifact references:

- one candidate-input handoff;
- one sanitized job observation;
- one specialist terminal intake;
- one specialist parsed TS/Freq result;
- one exact specialist TS mode review; and
- one specialist scientific decision.

Version 1 links only a specialist chain already classified
`ready_for_manual_mode_review` / `manual_review_required`, with one raw
imaginary mode and the exact review plus decision. Failed, incomplete,
zero-mode, or multiple-mode observations remain retained by their specialist
artifacts but are not coerced into this V1 accepted-decision link shape.

The link requires one consistent input hash across handoff, sanitized job, and
terminal intake; the sanitized source-job hash must equal the terminal
intake's job hash; and the parsed-result log hash must equal the terminal
intake's log hash. The mode review must hash-bind that exact parsed-result file
and reproduce its sole imaginary-mode frequency and displacement rows. The
decision must bind both that exact parsed-result file and the exact bound mode-
review file through `mode_review_sha256`. Scheduler, Gaussian, intake, parser,
and scientific-decision states are retained verbatim under
`preserved_classifications`. The adapter must not merge, reinterpret, or
promote those states and supplies no submit, retry, cancel, cleanup, or resume
behavior.

The link calls the TS specialist's `classify_ts_freq_terminal_facts` helper and
requires the recorded `outcome`, `acceptance_status`, first-order flag,
mode-review status, and `next_required_artifacts` to match its replay verbatim.

Before linking, parsed final-coordinate contiguous one-based indices and
ordered elements must equal the corresponding index/element projection of the
input handoff's reviewed `atom_order`; parsed results do not carry source atom
IDs, so this is not a second source-ID claim. Each parsed element must agree
with its atomic number in the supported V1 inventory, and each mode
displacement atomic number must agree with the corresponding final coordinate.
A fully rehashed but cross-inconsistent result/intake/review chain remains
invalid.

## DAG-owned binding implemented outside the adapter

The adapter deliberately defines no DAG node schema, plan mutation, node
state, dependency closure, approval state, or resume logic. The separate
narrow DAG-owned importer and binding review consume
`gaussian-candidate-target-import/1` and map each reviewed
`external_target_key` to the fixed node locator:

```json
{
  "study_id": "...",
  "plan_id": "...",
  "node_id": "..."
}
```

The calculation-DAG slice now implements the narrow `/1` importer described
here. It validates the target envelope and an exact
`gaussian-reaction-calculation-plan/1` reference, chooses the mapping under DAG
rules, and emits an append-only node update without mutating an existing plan.
No `node_id` is guessed or stored in this adapter's import envelope.

Facts attached to a bound node belong in the DAG-owned append-only
`gaussian-reaction-calculation-node-update/1` sidecar. Its contract owns
the same exact `{study_id, plan_id, node_id}` locator, node-kind consistency
metadata, the exact `target_plan` and mapping-review references, the exact
target import, and optional `supersedes`. Version `/1` is intentionally closed
to `candidate_inventory` / `candidate_target_import` for `ts_candidate`; later
roles or update kinds require a versioned extension. Those sidecars retain
`calculation_ready: false` and `no_submission_authorization: true`. The
adapter itself neither emits nor mutates a calculation plan; its only stable
DAG join key is `external_target_key`.
