# Asymmetric-catalysis offline data contract

Status: normative version 1 contract for offline artifacts. These artifacts are
non-runnable and grant no SSH, PBS, Gaussian, deployment, cancellation, or
server-data authority.

## 1. Files and schema IDs

| Artifact | Schema ID | Purpose |
| --- | --- | --- |
| study | `gaussian-asymmetric-catalysis-study/1` | chemical scope, hypotheses, protocols, channels, coverage dimensions, gates |
| candidate space | `gaussian-asymmetric-candidate-space-spec/1` | explicit boron/conformer/binding/approach levels and exclusions |
| candidate ledger | `gaussian-asymmetric-candidate-ledger/1` | deterministic enumeration, logical/geometry deduplication, materialization status |
| materializations | `gaussian-asymmetric-materializations/1` | reviewed local geometry and atom-map inputs |
| candidate | `gaussian-asymmetric-ts-candidate/1` | one geometry/state/channel hypothesis and its provenance |
| energy record | `gaussian-asymmetric-energy-record/1` | explicit, non-inferred comparison energy and thermochemical policy |
| result | `gaussian-asymmetric-ts-result/1` | immutable TS/Freq/mode/path evidence for one candidate |
| analysis | `gaussian-asymmetric-selectivity-analysis/1` | comparable ensemble, coverage, aggregation, uncertainty, claim |
| metal support | `gaussian-asymmetric-metal-support-design/1` | separate scientific checklist with mandatory submission refusal |
| metal TS audit template | `gaussian-asymmetric-metal-ts-audit-template/1` | candidate-bound atom/state/coordination/result-review boundary with mandatory submission refusal |
| literature benchmark | `gaussian-asymmetric-literature-benchmark-ledger/1` | hash-bound literature coordinates, identities, expected observables, and unresolved gates |
| smoke proposal | `gaussian-asymmetric-smoke-proposal/1` | priority-1 closed-shell main-group plan with no live authority |
| live-smoke evidence | `gaussian-asymmetric-live-smoke-evidence/1` | sanitized, hash-bound terminal/run/TS/mode evidence with no job ID, server path, log, or checkpoint |

The JSON Schemas are in `contracts/asymmetric-catalysis/`. Draft 2020-12
structural validity is necessary but not sufficient. Cross-file and scientific
rules in this document are normative and are checked offline by
`scripts/validate_asymmetric_contract.py` where implemented.

## 2. Common invariants

Every artifact must:

- use UTF-8 JSON with a recognized `schema` value;
- use stable IDs matching `^[a-z][a-z0-9_]{2,63}$`;
- use lowercase 64-character SHA-256 strings for immutable local dependencies;
- use one-based atom indices;
- use finite numeric values and explicit units;
- set `calculation_ready` to `false` and
  `no_submission_authorization` to `true` in version 1;
- preserve source artifacts rather than mutating them to record later review;
- contain no password, private key, SSH configuration, scheduler command, or
  remote-root override.

Paths may describe local evidence only. A path is never trusted instead of its
hash. Server project names and job IDs belong only in separately approved PBS
artifacts, not in version 1 candidates.

### 2.1 Literature benchmark ledger

A literature benchmark ledger is built from reviewed local XYZ files and an
explicit source specification. The builder must verify atom count, Hill
formula, exact XYZ SHA-256, canonical coordinate-block SHA-256, ordered-distance
geometry fingerprint, reaction-coordinate atom indices, and declared distances.

Reported observables and acceptance criteria are distinct fields. A featured
imaginary frequency printed in an SI figure does not establish that a new run
has exactly one raw imaginary frequency. Likewise, a literature statement that
IRC was used does not establish candidate-specific forward/reverse endpoints.

Missing source metadata remains null or explicitly unresolved. A proposed
neutral singlet may be recorded with its inference basis, but it requires
separate approval and does not become a source-reported charge/multiplicity.
The ledger must not contain a Gaussian route, rendered input, resources,
project, job ID, or submission authority.

### 2.2 Sanitized live-smoke evidence

Live-smoke evidence is a post-run summary, never a proposal or approval. It
binds the exact smoke proposal, literature ledger, three-tier protocol options,
explicit protocol selection, pre-submission approval, rendered input, job
record, parsed TS result, mode review, and mode decision by SHA-256. The source
artifacts remain under their owning Skills and are not copied into this
sanitized record.

`status: passed` requires all of the following:

- confirmed terminal state, verified transport hashes, a passed fresh-project
  guard, and reviewed resources;
- normal termination, no error termination, a stationary point, complete
  frequency evidence, and exactly one raw imaginary frequency; and
- an explicitly accepted, confirmed mode decision whose displacement was
  reviewed against the intended reaction coordinate.

Missing approval provenance or incomplete TS/mode evidence must remain
`incomplete` or `failed`. A run started before the three-tier protocol gate may
record null protocol-option/selection bindings only with `status: incomplete`;
never create a retrospective selection. The artifact contains no job ID,
server path, Gaussian log, or checkpoint. It authorizes neither a retry nor
IRC, another candidate, deployment, cancellation, or cleanup.

## 3. Study contract

### 3.1 Required identity and scope

A study records a stable `study_id`, title, objective, catalyst class, requested
selectivity types, temperature, standard state, species, catalyst states,
mechanism hypotheses, stereochemical channels, protocol sets, comparison
groups, coverage dimensions, unresolved questions, and review gates.

`status` is one of:

- `draft`: state space is still being defined;
- `reviewed_offline`: G0 completed, but no live authority exists;
- `superseded`: replaced by a new immutable study artifact.

### 3.2 Species and atom maps

Each species has a unique `species_id`. Charge and multiplicity refer to that
identity as represented. A catalyst-state composition references species IDs
and supplies integer stoichiometric counts. Its total charge/multiplicity are
explicit hypotheses, not automatically derived.

Stereochemical descriptors must distinguish `assigned`, `unassigned`, and
`not_applicable`. Axial, planar, helical, boron-centered, and relative
stereochemistry are allowed in addition to tetrahedral CIP descriptors.

### 3.3 Catalyst states

`catalyst_class` is one of:

- `metal_chiral_ligand`;
- `chiral_boron`;
- `metal_and_chiral_boron_cooperative`.

A metal-containing state must include `metal_centers`. A chiral-boron state must
include `boron_centers`. Cooperative states require both. Each center uses a
one-based atom index in the reviewed state structure.

An oxidation state, spin assignment, coordination number, boron coordination
state, or geometry marked `unknown` keeps the affected mechanism unresolved.
Version 1 metal states always remain unsupported for runtime promotion.

### 3.4 Mechanisms, channels, and comparison groups

Every mechanism references exactly one active catalyst state and at least one
stereochemical channel. Every coordinate change references one-based atom
indices and uses `forming`, `breaking`, or `transferring`.

Each comparison group specifies:

- one mechanism;
- two or more channels;
- one protocol set;
- one reference-state definition;
- one aggregation model;
- required validation level;
- applicable coverage-dimension IDs.

Channels are labeled chemically. `major` and `minor` are forbidden as channel
IDs because they are outputs of the analysis.

### 3.5 Protocols

Protocol fields are explicit user/reviewer inputs. Placeholder tokens such as
`<method>`, `TBD`, `TODO`, or `approved route` make a protocol unresolved.
Element-specific basis/ECP coverage must include every element used by a
promoted candidate. A protocol must not be copied between metal and main-group
systems without review.

The study may remain `draft` with unresolved protocols; in that state all
candidates must remain `proposed` and non-runnable.

## 4. Candidate contract

### 4.1 Candidate-space ledger

For chiral-boron enumeration, the space specification must include boron
center, boron coordination state, binding mode, catalyst conformer and approach
topology. The deterministic ledger records the full constrained product,
explicit exclusions, logical-equivalence keys and duplicate provenance.

Logical deduplication precedes geometry construction. Materialization requires a
real local XYZ file and a complete atom map; the builder computes the source
hash rather than accepting a claimed hash. Geometry equivalence is tested only
within the same catalyst state and channel. A cross-channel mirror or identical
distance matrix is never automatically collapsed.

Duplicate ledger entries remain evidence. Automatic duplicate detection sets a
candidate to `rejected`; it does not create a promotion decision.

One candidate belongs to exactly one study, mechanism, comparison group, and
channel. It records:

- immutable study file hash;
- active catalyst state and electronic-state hypothesis;
- binding mode, approach topology, conformer sources, and optional explicit
  solvent/additive placement;
- complete atom inventory and one-based atom map;
- source geometry path/hash;
- protocol ID and resource tier proposal;
- support status, review status, deduplication information, and coverage tags.

`support_status` is:

- `supported_main_group_closed_shell`;
- `unsupported_transition_metal`;
- `unsupported_electronic_structure`;
- `unresolved`.

`review_status` is `proposed`, `promoted_offline`, `rejected`, or `superseded`.
Promotion is allowed only when identities, state, stereochemistry, atom map,
charge, multiplicity, geometry hash, protocol, and candidate-space labels are
resolved. Promotion still leaves `calculation_ready: false`.

For metal candidates, version 1 requires
`support_status: unsupported_transition_metal`. For a closed-shell chiral-boron
candidate, `supported_main_group_closed_shell` is allowed only if the scientific
state is otherwise within `auto-g16-ts-irc` scope.

### 4.1 Transition-metal support-design artifact

`gaussian-asymmetric-metal-support-design/1` is a deterministic, hash-bound scientific
design artifact, not a runnable candidate. It must preserve the study's exact
metal-center and formal-oxidation-state declarations without deriving a
d-electron count, spin state, charge or coordination assignment from another
field. Each catalyst state contains unresolved review blocks for:

- oxidation state and electron accounting;
- multiplicity and competing spin surfaces;
- restricted/unrestricted or broken-symmetry wavefunction treatment, stability
  and spin-contamination checks;
- coordination number, geometry, hapticity, counterion and association state;
  and
- method, per-element basis/ECP, relativistic, solvation, dispersion, grid and
  SCF policy.

Each declared mechanism produces exactly one search family containing the
Hessian-guided single-guess, endpoint-bound QST2/QST3 and reviewed relaxed-scan
strategies. All three have `status: design_candidate_not_selected`. The family
must name its catalyst state, stereochemical channels and intended coordinates;
unassigned elementary-step class or unresolved reaction-surface model blocks
selection.

Milestone `M0` records the implemented offline design/refusal audit, and
`metal_m2a_candidate_audit_template` records the implemented candidate-bound
audit-template layer. `M1`, the remaining `M2`, `M3` and `M4` work cover a
bounded scientific state review, structured result/parser checks, execution
boundary and a separately approved smoke test. They remain blocked or pending.
The artifact always carries
`submission_decision: refused`, `calculation_ready: false` and
`no_submission_authorization: true`; filling review fields cannot change those
values.

`duplicate_of` may reference another candidate only when the chemical state,
channel, atom map, stereochemistry, and geometry equivalence have been reviewed.
Candidates in different stereochemical channels are never deduplicated solely
by RMSD.

## 5. Result contract

A result is immutable and references the exact candidate artifact hash plus the
input, log, checkpoint when present, parsed TS result, mode review, and mode
decision hashes.

`validation_level` is derived, never chosen aspirationally:

- `failed`: the calculation or evidence gate failed;
- `first_order_saddle_candidate`: normal stationary/frequency evidence and
  exactly one raw negative frequency;
- `mode_reviewed`: the preceding conditions plus an accepted, hash-bound mode
  decision;
- `path_validated`: the preceding conditions plus two completed, structurally
  identified path directions and reviewed endpoints.

The following implications are mandatory:

```text
validation_level >= first_order_saddle_candidate
  => normal_termination == true
  => stationary_point == true
  => frequency_complete == true
  => raw_imaginary_frequency_count == 1

validation_level >= mode_reviewed
  => mode_decision == accepted

validation_level == path_validated
  => forward_path == completed_and_identified
  => reverse_path == completed_and_identified
```

Only `mode_reviewed` or `path_validated` results may enter an energetic
selectivity analysis, and the comparison group's required validation level may
be stricter.

Energies are separated into electronic energy, thermal corrections, and the
declared comparison energy. A composite energy must name the exact formula and
source protocol IDs. Low-frequency corrections are never implied by a field
named `gibbs`.

## 6. Analysis contract

An analysis references one exact study and comparison group plus the hashes of
every included/excluded candidate result.

### 6.1 Comparability

Every included result must have:

- a channel in the comparison group;
- the same protocol and energy definition;
- the required validation level;
- the same temperature and standard state;
- a common atom inventory or a reviewed balanced reference cycle;
- no unresolved warnings that invalidate comparison.

An analysis that fails these checks uses `status: blocked_incomparable` and has
no predicted selectivity claim.

### 6.2 Coverage

Coverage is recorded by declared dimension, never as an invented percentage.
Each applicable dimension lists expected and observed levels, exclusions, and
one of `complete`, `reviewed_pruned`, `incomplete`, or `unknown`.

`validated` requires all applicable dimensions to be `complete` or
`reviewed_pruned`. `provisional` may retain incomplete dimensions only when they
are listed in `claim_limitations`. `inconclusive` is used when plausible
alternatives or sensitivity reverse/erase the ordering.

### 6.3 Aggregation

Allowed aggregation models are:

- `boltzmann_ts_ensemble`;
- `lowest_ts_only_sensitivity`;
- `kinetic_network_external`.

For `boltzmann_ts_ensemble`, use a common energy zero and record each candidate's
comparison free energy and positive degeneracy. The analysis records `R`, `T`,
units, channel weights, effective channel barriers, and normalized channel
fractions. An implementation must use a log-sum-exp form for numerical
stability.

`lowest_ts_only_sensitivity` can never produce `status: validated` by itself.
`kinetic_network_external` records a hash-bound external model/result and does
not reuse the simple two-channel equation.

For exactly two enantiomeric channels, the sign convention is:

```text
delta_delta_g_kcal_mol = G_eff(minor) - G_eff(major)
```

The named major channel must therefore have the lower effective barrier. A
positive value predicts enrichment of the named major channel. Multi-channel
analyses report channel fractions first; any ee/dr grouping is explicit.

### 6.4 Claim status

- `validated`: contract, comparability, required validation, and coverage gates
  all pass within the stated mechanism/model;
- `provisional`: calculation is internally comparable but path, coverage, or
  sensitivity evidence is intentionally limited;
- `incomplete`: required artifacts are absent;
- `inconclusive`: available evidence does not support a stable ordering;
- `blocked_incomparable`: reference/protocol/inventory mismatch;
- `failed`: analysis artifact is internally invalid.

No status authorizes live work.

## 7. Immutability and supersession

Review decisions and analyses are new files bound by hashes. Do not edit a
candidate result to record later acceptance, and do not edit a completed
analysis when a new conformer appears. Create a superseding artifact and retain
the old one.

The validator hashes raw file bytes. Reformatting a referenced JSON file changes
its SHA-256 and correctly invalidates downstream bindings.

## 8. Offline validator usage

The repository validator uses only the Python standard library:

```bash
python3 scripts/validate_asymmetric_contract.py \
  --study tests/fixtures/asymmetric_catalysis/boron_study.json \
  --candidate tests/fixtures/asymmetric_catalysis/boron_candidate.json
```

Standalone artifacts, including a sanitized live-smoke record, use repeatable
`--artifact` arguments:

```bash
python3 scripts/validate_asymmetric_contract.py \
  --artifact path/to/sanitized-live-smoke-evidence.json
```

It performs no network or subprocess operation. A successful exit means the
implemented structural/semantic checks passed; it is not scientific approval
and does not prove that the candidate search is complete.

The deterministic builder is also standard-library only:

```bash
python3 skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py --help
```

`ingest-result` derives validation levels from existing `auto-g16-ts-irc`
evidence and hash-bound review decisions. `aggregate` uses log-sum-exp and emits
lowest-TS-only, adversarial energy-shift, and leave-one-out sensitivity where
applicable. Its highest automatic status is `provisional`.
