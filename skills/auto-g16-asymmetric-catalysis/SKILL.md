---
name: auto-g16-asymmetric-catalysis
description: Plan and audit literature-grounded transition-state ensembles for asymmetric organic methodology involving chiral boron catalysts or transition metals with chiral ligands. Use when defining active catalyst states, stereochemical channels, conformer and binding-mode coverage, TS validation evidence, common-reference thermochemistry, or predicted ee/dr/regioselectivity. This is an offline scientific-orchestration Skill; it does not choose a DFT method, authorize Gaussian/PBS execution, or bypass unsupported transition-metal and electronic-structure cases.
---

# Auto-G16 Asymmetric Catalysis

## Purpose

Turn a reviewed asymmetric-catalysis hypothesis into an auditable candidate and
evidence plan. Treat selectivity as a comparison between covered ensembles of
chemically comparable transition structures, not as one hand-built major/minor
pair.

This Skill covers two classes in the following development priority:

1. transition-metal catalysis with a chiral ligand, currently as a detailed
   deterministic offline TS-capability design with execution refused; and
2. chiral boron Lewis-acid, borane, borate, or multi-boron catalysis after the
   transition-metal design milestone.

## Read the relevant references

- Read `references/wang-group-computational-precedents.md` when the request
  concerns Xiao-Chen Wang group chemistry, borane/pyridine methodology,
  borane/metal cooperative catalysis, or asks what earlier calculations did.
- Read `references/candidate-and-selectivity-protocol.md` before creating or
  reviewing a study, candidate inventory, TS search plan, or selectivity claim.
- Read `references/transition-metal-support-design.md` for every transition-
  metal or metal/chiral-boron cooperative case.
- Read `references/transition-metal-computational-strategy-evidence.md` before
  proposing transition-metal model families, parser fields or extension
  milestones. Its literature records are evidence and analogies, not defaults.
- Read `references/wang-2025-borane-nickel-m1-gap-audit.md` before using DOI
  `10.1021/jacs.5c13835` as an M1 example. It records the exact evidence ceiling
  and why no real candidate-bound M1 artifact can yet be created.

The literature reference records verified precedents and evidence gaps. It is
not a menu of default methods.

## Non-negotiable boundaries

- Do not infer a functional, basis/ECP, solvent model, dispersion correction,
  grid, SCF strategy, spin state, broken-symmetry state, TS algorithm, IRC
  settings, temperature, standard state, or low-frequency treatment.
- After a calculation need is defined and before any Gaussian input is written,
  require the core protocol-rigor workflow to create
  `gaussian-protocol-options/1` with `loose`, `standard` and `strict`, and
  record the user's separate hash-bound `gaussian-protocol-selection/1`.
  Mark unresolved or unsupported candidates `blocked`; do not fill a tier by
  inferring chemistry. `strict` is a stronger evidence/sensitivity plan, not an
  accuracy guarantee, and it is independent of the PBS resource tier.
- Do not infer an active catalyst from a precatalyst drawing. Record ligand
  count, coordination, protonation, counterion, aggregation, additive and
  substrate binding as explicit hypotheses.
- Do not submit or retry a calculation from this Skill. A study artifact is
  offline evidence and never live authorization.
- Preserve the `auto-g16-ts-irc` refusal of transition-metal,
  broken-symmetry, excited-state, multireference, periodic, and ONIOM cases.
  Mark such candidates `unsupported_requires_extension` and
  `calculation_ready: false`.
- Keep any later server work below `/home/user100/SDL` and require the existing
  structure, stereochemistry, charge, multiplicity, route, resources,
  fresh-directory, and input-hash approval gates.
- Never claim a TS from frequency count alone. Require exactly one raw
  imaginary frequency and explicit normal-mode review against the intended
  bond-forming, bond-breaking, or transferring coordinate.
- Never claim path validation until both approved IRC directions terminate and
  their endpoints are structurally identified.

## Workflow

All implemented commands use only the Python standard library and refuse to
overwrite an existing output. Run them from the repository source of truth:

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py --help
```

For a reviewed literature reproduction, build the immutable coordinate and
expectation ledger before creating any study-specific calculation proposal:

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  build-literature-benchmark studies/wang_2024_bf3_ts/benchmark-source.json \
  --output candidate-ledger.json
```

The builder verifies atom count, Hill formula, exact XYZ hash, a canonical
coordinate-block hash, geometry fingerprint, declared reaction-coordinate
distances, literature values, and unresolved scientific gates. It does not
emit a Gaussian input or infer missing source metadata.

### 1. State the scientific question

Record the reaction, experimental selectivity, proposed selectivity-determining
step, competing mechanisms, product channels, and the evidence for treating
that step as selectivity determining. Distinguish this from the turnover-
limiting step.

If the mechanism or active species is unresolved, create competing hypotheses;
do not silently select one.

### 2. Define complete catalyst states

For chiral boron systems, enumerate relevant boron centers, coordination
numbers, Lewis adducts, B(sp2)/B(sp3) states, catalyst-formation diastereomers,
substrate/additive binding modes, aggregation and ion pairing. Nominally
similar boron atoms may be diastereotopic.

For metal/chiral-ligand systems, record metal identity, oxidation-state
hypothesis, total charge and multiplicity, ligand identity and conformation,
coordination geometry, hapticity, labile sites, counterion placement and every
spin/coordination alternative included or excluded. Stop promotion when
broken-symmetry or multireference concerns are unresolved.

Immediately run `design-metal-support` for a metal study. Treat its output as
the primary capability artifact: it expands every metal state into explicit
electron-accounting, spin, wavefunction, coordination and method-review
blocks, and every mechanism into three unselected TS seed-strategy candidates
(Hessian-guided single guess, reviewed QST2/QST3, and reviewed relaxed scan).
It must retain all blockers and the unconditional execution refusal.

After a concrete unsupported metal candidate exists, run
`build-metal-ts-audit-template` with the exact metal-support design and
candidate. The template binds atom order, metal centers, intended coordinate,
coordination contacts and the complete three-strategy inventory. It leaves
d-electron counts, coordination distance windows and every scientific audit
section blocked. Do not fill those fields by editing the template or treat the
template as an input-preparation artifact.

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  build-metal-ts-audit-template METAL-SUPPORT.json CANDIDATE.json \
  --output METAL-TS-AUDIT-TEMPLATE.json
```

Use `build-metal-scientific-review` to freeze reviewer-supplied M1 values in a
separate sidecar. It binds the exact support design, still-blocked M2a template,
unsupported candidate and review source. It never edits or unlocks those input
artifacts. Every non-null oxidation/electron-count, spin, wavefunction,
coordination, method and TS-design value must already exist in the review
source and cite a source locator.

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  build-metal-scientific-review METAL-SUPPORT.json \
  METAL-TS-AUDIT-TEMPLATE.json CANDIDATE.json REVIEW-SOURCE.json \
  --output METAL-SCIENTIFIC-REVIEW.json
```

A complete synthetic fixture proves only that the offline contract works and
records `metal_m1_scientific_review_status: not_satisfied_synthetic_fixture`;
it does not satisfy `metal_m1_scientific_review`. A complete real review record
still has `scientific_acceptance_decision: not_granted_by_artifact`, keeps the
candidate unsupported and cannot select a protocol or execution strategy.
M1 scope is evidence-bound: synthetic scope accepts only synthetic-fixture
sources, primary-literature scope accepts only primary article/SI sources, and
mixed scope requires both primary and reviewer-record sources while forbidding
synthetic fixtures.
`--dry-run` validates the full lineage and reports `live_actions: false`
without writing a file.

When an existing local Gaussian input is available for offline audit, use
`audit-metal-input` to bind its exact SHA-256 to the candidate, still-blocked
M2a template and M1 sidecar. The command parses only a single-step explicit
Cartesian input and observes Link 0 directives, route text, charge,
multiplicity, atom order, coordinate-block hash, task-keyword text and a hash
of any uninterpreted trailing section.

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  audit-metal-input METAL-TS-AUDIT-TEMPLATE.json CANDIDATE.json \
  METAL-SCIENTIFIC-REVIEW.json EXISTING.gjf \
  --output METAL-INPUT-OBSERVATION.json
```

It never renders or modifies the input, never treats route text as a selected
protocol, and never accepts a basis/ECP, solvent, electronic state, TS task or
server path. Multi-step `--Link1--`, charge/multiplicity drift, atom-order
drift and `Geom=Check/AllCheck` ambiguity are rejected. All six scientific
sections, input acceptance, promotion, submission and execution remain
blocked. `--dry-run` performs the same checks without writing a file.

```text
metal_m2c_input_observation: implemented_offline
input_acceptance_decision: not_granted_by_artifact
protocol_selection_decision: absent_not_authorized
```

When an existing local Gaussian log is supplied strictly for offline software
development or retrospective evidence intake, `audit-metal-result` binds it to
the exact template and candidate. It parses identity, termination, raw
frequency, `S**2`/stability-message and declared coordination-distance
observations. Every scientific audit remains blocked even when the log has
normal termination and exactly one imaginary frequency.

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  audit-metal-result METAL-TS-AUDIT-TEMPLATE.json CANDIDATE.json EXISTING.log \
  --output METAL-RESULT-OBSERVATION.json
```

This command is read-only apart from creating the new local JSON artifact. It
does not accept a TS, parse a mode displacement, render an input, call another
Skill, or authorize any live action.

Use `--dry-run` without `--output` to exercise the complete parse and refusal
checks while writing no artifact. The JSON summary always reports
`live_actions: false`.

Use `build-metal-acceptance-review` to record four independent reviewer
decisions after M1, M2a, M2b and M2c exist: wavefunction, coordination, mode,
and input acceptance. The source must bind every upstream artifact hash and
each section must be explicitly accepted for bounded offline review, rejected,
or blocked for missing evidence.

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  build-metal-acceptance-review METAL-TS-AUDIT-TEMPLATE.json CANDIDATE.json \
  METAL-SCIENTIFIC-REVIEW.json METAL-INPUT-OBSERVATION.json \
  METAL-RESULT-OBSERVATION.json DECISION-SOURCE.json \
  --output METAL-ACCEPTANCE-REVIEW.json
```

`accepted_for_bounded_offline_review` is a reviewer record inside one section,
not top-level scientific or execution acceptance. Every output keeps
`scientific_acceptance_decision`, `input_acceptance_decision` and
`mode_acceptance_decision` at `not_granted_by_artifact`, keeps promotion and
submission refused, and cannot authorize IRC or a live action. A complete
synthetic fixture records `not_satisfied_synthetic_fixture`. `--dry-run`
performs the same lineage and evidence checks without writing an artifact.
A real M2d scope additionally requires a completed non-synthetic real M1,
a non-empty reviewer, a valid ISO calendar date, and no `synthetic_fixture`
evidence in any decision section.

```text
metal_m2d_acceptance_review_contract: implemented_offline
```

### 3. Build the candidate matrix

Construct candidates from the applicable Cartesian product:

```text
mechanism x catalyst state x stereochemical channel x binding mode
x catalyst conformer x substrate conformer x approach topology
x ion-pair/additive placement x electronic-state hypothesis
```

Give every level a stable identifier. Record expected levels, generated
candidates, exclusions, reviewer decisions, immutable structure hashes and
deduplication provenance. Do not collapse mirror-related structures in a
chiral environment.

Use `build-study`, then `enumerate-boron` to create the immutable candidate-
space ledger. The enumerator requires explicit boron-center, boron-
coordination-state, binding-mode, catalyst-conformer and approach-topology
dimensions. Use `build-candidates` only after real local XYZ files and their
complete atom maps are available. Logical equivalence is resolved first;
geometry duplicates use ordered atom-pair distances only within the same
channel and catalyst state. Automatically detected duplicates are rejected,
never promoted.

### 4. Approve one comparison protocol

Require an explicit and reviewed optimization/frequency, single-point,
solvation, thermochemistry and path-validation stack. All compared members
must share atom inventory or a balanced reference cycle, protocol,
temperature, standard state, low-frequency policy and energy zero.

First create the three-candidate protocol proposal for the stated calculation
and claim, then record the user's selection before rendering any input. The
selection authorizes only the exact offline input draft. It does not authorize
submission, a TS retry, either IRC direction, an endpoint or another candidate.
Choose `simple`, `general` or `complex` resources separately from protocol
rigor.

Literature settings may justify candidates for a benchmark matrix, but never
become defaults for a new reaction.

### 5. Validate each TS family

For every promoted candidate require:

1. stationary-point and complete frequency evidence;
2. exactly one raw imaginary frequency;
3. a hash-bound review that the mode follows the declared coordinate;
4. separately approved forward and reverse IRC when supported;
5. identified endpoint structures rather than direction labels alone; and
6. retained records for failed, duplicate, wrong-mode, or unresolved cases.

Delegate supported closed-shell main-group TS evidence to
`auto-g16-ts-irc`. Use `auto-g16-view-rt-win` for visible structure and mode
review, and `auto-g16-rtwin-pbs` only after a separate exact live approval.

### 6. Aggregate comparable ensembles

Use all retained, comparable TS conformers under an explicitly approved
Curtin-Hammett/TST model:

```text
W(channel) = sum_i degeneracy_i * exp[-(G_TS,i - G_reference)/(R*T)]
G_eff_dagger(channel) = -R*T*ln(W(channel))
```

For two channels define the sign convention before calculating a ratio or ee.
Use a kinetic network instead when catalyst states do not equilibrate rapidly,
steps are reversible, products interconvert, or several steps control
selectivity.

Report coverage, missing plausible candidates, sensitivity to protocol and
thermochemistry, and whether one missing candidate could reverse the ordering.
Label lowest-TS-only results as sensitivity analyses.

Use `ingest-result` only for a `promoted_offline` candidate. It binds the
existing `auto-g16-ts-irc` TS result `/2`, mode review and explicit mode
decision to an energy record. New `path_validated` and comparison eligibility
require `--path-acceptance` with canonical owner replay of
`gaussian-ts-irc-path-acceptance/2`, including both endpoint-structure reviews
`/2`, the current study/mechanism states, attempt/terminal/fetch evidence and
shared TS-checkpoint lineage. Historical endpoint-audit `/1`, direct
`--forward-audit`/`--reverse-audit`, or direction/side labels are display-only
and never grant eligibility.

```bash
python skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py ingest-result \
  CANDIDATE.json TS_RESULT_V2.json ENERGY.json \
  --mode-review MODE_REVIEW.json --mode-decision MODE_DECISION.json \
  --path-acceptance PATH_ACCEPTANCE_V2.json --output RESULT.json
```

Use `aggregate` for log-sum-exp Boltzmann aggregation, two-
channel ee, lowest-TS-only, adversarial energy-shift and leave-one-out
sensitivity. This builder accepts only a study whose aggregation model is
`boltzmann_ts_ensemble`; kinetic-network and lowest-TS-only models require a
different implementation. Every result must bind to the promoted candidate
artifact and hash recorded by the ledger, and all energies, temperatures and
degeneracies must be finite and valid. Automatically generated analyses remain
`provisional` at best; only a separate reviewer decision can validate a claim.

For a metal study, use `design-metal-support` to produce the refusal-preserving
state-space and TS-search design. Validate its payload hash, exact study/state/
mechanism bindings, complete three-strategy inventory, cross-state separation
rules and extension milestones. Do not select a strategy, infer an elementary-
step class, write a route or hand the artifact to an execution Skill.

For an individual metal candidate, use `build-metal-ts-audit-template` to
freeze the future result-review boundary. Validate its payload, source hashes,
atom order, metal-center identities, candidate coordination contacts, six
blocked audit sections and unselected strategy inventory. It establishes no
TS claim and cannot be promoted or submitted.

Use `build-metal-scientific-review` only as the candidate-bound M1 sidecar.
Validate both its reviewer-source schema and its output payload. Reviewed
sections must have closed evidence references; blocked sections must retain
their reasons. The M2a template must remain blocked and its strategy gate must
remain unselected. The sidecar claim ceiling is
`bounded_review_record_only_no_scientific_acceptance_ts_or_selectivity_claim`.
Literature methods remain evidence for the exact reported example and are
never converted into defaults.

Use `audit-metal-input` only for an already existing local input. Validate its
payload and refusal flags as
`gaussian-asymmetric-metal-input-observation/1`. Matching charge,
multiplicity and element order proves only identity consistency; route,
Link 0 and trailing-section observations do not constitute protocol selection,
input acceptance or remote path approval. The artifact claim ceiling is
`existing_input_observation_only_no_acceptance_execution_ts_or_selectivity_claim`.

Use `audit-metal-result` only to preserve candidate-bound facts from an
existing local log. Validate its payload and refusal flags as
`gaussian-asymmetric-metal-result-observation/1`. Exactly one observed raw
imaginary frequency, an `S**2` line, a stability message or an unchanged
distance does not pass electron, spin, wavefunction, coordination, method, mode
or path review. The artifact claim ceiling remains
`parsed_observation_only_no_ts_or_selectivity_claim`.

Use `build-metal-acceptance-review` only for explicit human decisions. An
accepted wavefunction section requires hash-bound stability, spin,
occupation/alternative-solution and multireference assessments; coordination
requires complete contact, hapticity and ligand-inventory review; mode requires
exactly one observed imaginary frequency plus hash-bound displacement review;
and input acceptance requires exact input, protocol options/selection, input
approval, input/result lineage and server-path/resource review hashes. Missing
evidence remains blocked and is never inferred. The sidecar claim ceiling is
`manual_decision_record_only_no_runtime_promotion_ts_path_or_selectivity_claim`.

After all offline tests pass, `propose-smoke` may bind the reviewed priority-1
closed-shell main-group literature candidate into a plan with
`status: planned_not_submitted`. If route, solvent, charge/multiplicity,
thermochemistry, resources, or project metadata are unresolved, the proposal
must keep them null and must not render an input. This command does not submit,
create a server directory, or approve any protocol.

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  propose-smoke studies/wang_2024_bf3_ts/candidate-ledger.json \
  --candidate-id wang2024_bf3_ts1 \
  --output docs/asymmetric-catalysis-smoke-proposal.json
```

If a separately approved live smoke run later reaches a terminal state, keep
the full input, job, log, checkpoint, parsed TS, mode-review and decision
artifacts in their owning execution/TS Skills. Record only a sanitized
`gaussian-asymmetric-live-smoke-evidence/1` summary here, with SHA-256 bindings
to the exact proposal, protocol options, protocol selection, input approval,
input and evidence chain. Validate it with
`scripts/validate_asymmetric_contract.py --artifact`. Never mark it `passed`
without prospective protocol-selection provenance, normal termination,
complete frequencies, exactly one raw imaginary mode, and an explicitly
accepted coordinate-displacement review. This evidence does not authorize a
retry, IRC, another candidate, deployment, cancellation, or cleanup.

The successful BF3-TS1 `r01` recovery and the in-flight BF3-TS2-B1 job have
their own prospective, hash-bound protocol and live-approval evidence. Do not
reuse either approval for a retry, BF3-TS2-B2, IRC, endpoint or another
candidate. Apply a fresh three-tier gate and exact approval to every such
action.

## Claim levels

- `first_order_saddle_candidate`: stationary point, complete frequency, one
  raw imaginary mode.
- `mode_consistent_ts`: candidate plus accepted displacement review.
- `path_validated_ts`: mode-consistent TS plus identified endpoints in both
  approved directions.
- `provisional_selectivity`: comparable reviewed ensembles with bounded gaps
  or missing path evidence.
- `validated_selectivity_under_stated_model`: common reference and protocol,
  complete or reviewed-pruned coverage, required TS/path evidence and explicit
  aggregation model.

Do not shorten the final phrase to “validated mechanism” or “validated ee.”

## Expected outputs

Produce or update the versioned offline artifacts described by the repository
contract:

- study scope and catalyst/mechanism/channel hypotheses;
- one record per proposed or promoted TS candidate;
- parsed and hash-bound TS/mode/path evidence; and
- coverage, aggregation, uncertainty and claim-level analysis.

The candidate-space, ledger, materialization, explicit-energy, metal-support,
metal-TS-audit-template, metal-scientific-review-source,
metal-scientific-review, metal-input-observation, metal-result-observation,
metal-acceptance-review-source, metal-acceptance-review, smoke-proposal, and
sanitized live-smoke-evidence artifacts are defined in
`contracts/asymmetric-catalysis/`. Neither the proposal nor the evidence record
grants live authority.

End with a prioritized gap list. For the current roadmap, prioritize transition-
metal active/electronic-state review, coordination inventory, TS seed-strategy
selection criteria and a real candidate-bound M1 record. The M1 sidecar
contract is implemented, but the real scientific milestone remains pending.
The read-only M2c observer and M2d four-section manual-decision sidecar are
implemented. Next prioritize one real field-complete M1/M2 review and M3
adversarial execution-boundary design; section decisions must not turn into
promotion or live authority. Keep B1
terminal/mode acceptance as an independent evidence gate, and defer the real
chiral-boron candidate-space study until the metal design milestone is
complete.
