---
name: gaussian-asymmetric-catalysis
description: Plan and audit literature-grounded transition-state ensembles for asymmetric organic methodology involving chiral boron catalysts or transition metals with chiral ligands. Use when defining active catalyst states, stereochemical channels, conformer and binding-mode coverage, TS validation evidence, common-reference thermochemistry, or predicted ee/dr/regioselectivity. This is an offline scientific-orchestration Skill; it does not choose a DFT method, authorize Gaussian/PBS execution, or bypass unsupported transition-metal and electronic-structure cases.
---

# Gaussian Asymmetric Catalysis

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
- Preserve the `gaussian-ts-irc` refusal of transition-metal,
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
python3 skills/gaussian-asymmetric-catalysis/scripts/asymmetric_catalysis.py --help
```

For a reviewed literature reproduction, build the immutable coordinate and
expectation ledger before creating any study-specific calculation proposal:

```bash
python3 skills/gaussian-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
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
`gaussian-ts-irc`. Use `gaussian-view-rt-win` for visible structure and mode
review, and `gaussian-rtwin-pbs` only after a separate exact live approval.

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
existing `gaussian-ts-irc` TS result, mode review and explicit mode decision to
an energy record. When endpoint audits are supplied, also require the exact TS
input, log, checkpoint, passed checkpoint-geometry audit and bidirectional IRC
plan. The candidate atom order, charge and multiplicity must match the TS,
checkpoint audit and both endpoint audits; the IRC plan must bind the same TS,
mode decision and checkpoint hashes and map each direction to the endpoint's
exact project. Passed direction/side labels alone never grant
`path_validated` status.

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

After all offline tests pass, `propose-smoke` may bind the reviewed priority-1
closed-shell main-group literature candidate into a plan with
`status: planned_not_submitted`. If route, solvent, charge/multiplicity,
thermochemistry, resources, or project metadata are unresolved, the proposal
must keep them null and must not render an input. This command does not submit,
create a server directory, or approve any protocol.

```bash
python3 skills/gaussian-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
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
smoke-proposal, and sanitized live-smoke-evidence artifacts are defined in
`contracts/asymmetric-catalysis/`. Neither the proposal nor the evidence record
grants live authority.

End with a prioritized gap list. For the current roadmap, prioritize transition-
metal active/electronic-state review, coordination inventory, TS seed-strategy
selection criteria, metal-specific offline parsers and refusal tests. Keep B1
terminal/mode acceptance as an independent evidence gate, and defer the real
chiral-boron candidate-space study until the metal design milestone is
complete.
