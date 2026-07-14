# Transition-metal transition-state capability design

Treat this as an offline scientific design and refusal contract. Do not extend
the execution scope of `gaussian-ts-irc`, generate a Gaussian route or input,
or authorize a metal job.

## Boundary

Keep every metal/chiral-ligand or metal/chiral-boron cooperative state at:

```text
runtime_support_status: unsupported_requires_extension
submission_decision: refused
calculation_ready: false
no_submission_authorization: true
```

Run only the offline design command:

```bash
python3 skills/gaussian-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  design-metal-support STUDY.json --output METAL-SUPPORT.json
```

Use its output to inventory electronic states, coordination alternatives,
transition-state seed strategies, blockers and extension milestones. Never
hand the artifact to an execution Skill.

## Design graph

Build a metal TS study from the following reviewed product, not from one
precatalyst drawing:

```text
elementary-step hypothesis
x oxidation/electron-count state
x charge and multiplicity
x wavefunction hypothesis
x nuclearity and coordination geometry
x ligand count, denticity, hapticity and conformation
x substrate/counterion/solvent binding mode
x stereochemical channel and approach topology
x TS seed strategy
```

Preserve each change in oxidation state, charge, multiplicity, nuclearity,
coordination number, hapticity, ligand count or wavefunction as a separate
state. Never merge candidates across those boundaries by RMSD or a distance
fingerprint.

## 1. Oxidation state and electron count

Record, without inferring from the element symbol:

- formal oxidation state per metal;
- ligand charge convention and non-innocent alternatives;
- d-electron count per metal;
- total electron count and parity;
- total molecular charge and multiplicity;
- metal-metal bonding convention for polynuclear states; and
- the evidence or model assumption behind every assignment.

Cross-check electron parity against the proposed multiplicity. Treat a formal
oxidation state as a bookkeeping hypothesis, not a wavefunction diagnosis.
Keep `d_electron_count` null in the generated design until a reviewer supplies
the ligand-charge convention and confirms the count.

## 2. Spin-state and surface space

List every chemically credible multiplicity for each oxidation/coordination
state. Define a common reference for relative spin-state energies. Record
whether spin crossover, two-state reactivity or a minimum-energy crossing point
could enter the elementary step.

Do not:

- use a singlet because the structure has even electron parity;
- compare different spin surfaces with inconsistent reference states;
- put different spin surfaces in one Boltzmann TS ensemble; or
- describe an ordinary single-surface TS/IRC as proof of a spin-crossing path.

When a crossing is mechanistically relevant, stop. A future extension needs a
separate MECP/crossing and kinetic model; the current TS/IRC layer cannot
represent it.

## 3. Wavefunction hypotheses and checks

Require an explicit restricted, unrestricted, restricted-open-shell or
broken-symmetry hypothesis. Before accepting any future energy or gradient,
require a state-specific policy for:

- SCF stability analysis;
- `<S^2>` and spin-contamination thresholds;
- alternative broken-symmetry solutions;
- occupation and orbital-character inspection;
- wavefunction reuse between geometries;
- multireference diagnostics appropriate to the metal/electron count; and
- rejection or escalation when single-reference evidence is inadequate.

SCF convergence is not electronic-state validation. Do not reuse a checkpoint,
Hessian or guess between spin/wavefunction hypotheses without a separately
reviewed provenance map.

## 4. Coordination and catalyst-state audit

Record and review:

- nuclearity and metal-metal contacts;
- coordination number and geometry per center;
- ligand identity, stoichiometry, denticity, hapticity and hemilability;
- labile, vacant and solvent-occupied sites;
- substrate binding atom(s), face and orientation;
- counterion identity, contact/separated ion pairing and placement;
- explicit solvent/additive occupancy;
- agostic, secondary-sphere and weak coordination contacts; and
- alternative associated/dissociated states.

Preserve a one-based coordination map independently of covalent bond
perception. Audit metal-ligand distances, hapticity and coordination-number
changes after every future optimization. A calculation that silently loses a
ligand, counterion or substrate binding mode is a different state, not the
requested candidate.

## 5. Elementary-step classification

Require the reviewer to assign the elementary-step class and intended
coordinate changes. Possible classes include oxidative addition, reductive
elimination, migratory insertion, beta-hydride elimination, ligand
association/dissociation, transmetalation, proton transfer and outer-sphere
bond formation, but never select a class from geometry alone.

For each mechanism, record:

- reactant and product state identities;
- atom map and forming/breaking/transferring pairs;
- oxidation/spin/coordination changes across the step;
- whether one electronic surface is assumed;
- stereochemical channels and topicity; and
- evidence that the step controls selectivity.

## 6. TS seed-strategy candidates

Generate all three strategy records for review. Do not select one
automatically.

### Hessian-guided single guess

Require a reviewed TS-like geometry, intended coordinate map, electronic and
coordination state, and Hessian provenance. Record the risk of converging to a
wrong saddle, ligand-loss mode or alternative coordination state.

### Endpoint QST2/QST3

Require reviewed endpoints on the same electronic surface, identical element
and atom order, explicit atom correspondence, compatible charge/multiplicity,
and raw multi-structure syntax verified for the installed Gaussian revision.
Do not use QST to hide unresolved spin crossing or coordination changes.

### Reviewed relaxed-coordinate scan

Require explicit scan coordinate(s), direction, step policy, constraints that
preserve coordination and stereochemistry, and a separate rule for promoting a
scan maximum to a TS guess. Treat a one-dimensional scan as potentially
incomplete when coordinates are coupled. The current workflow has no metal
scan execution backend.

Other algorithms such as NEB/string methods or MECP searches require a new
explicit strategy type, parser, evidence contract and software boundary. Do
not encode them as one of the three existing strategies.

## 7. Candidate-bound offline audit template

After a concrete candidate artifact exists, bind it to the exact metal-support
design with `build-metal-ts-audit-template`. Require matching study, state,
mechanism and channel IDs; exact source SHA-256 values; contiguous one-based
atom order; matching metal-center identities; candidate coordination contacts;
and the unchanged three-strategy inventory.

The template is deliberately incomplete. Keep every coordination distance
window and d-electron count null, every audit section
`blocked_pending_review`, and the seed strategy unselected. Its six sections
separately gate electron accounting, spin/surface space, wavefunction,
coordination, method protocol, and TS/path evidence. It may be used to design a
future parser or result reviewer, but never to render an input.

Reject a template when its source hash, atom order, metal identity, candidate
contact inventory or strategy inventory drifts. Even a structurally valid
template has claim ceiling `design_only_no_ts_or_selectivity_claim`.

## 8. Method and basis protocol

Apply the three-tier protocol gate only after the chemical and electronic
state is reviewed. Require explicit:

- basis/ECP coverage for every element;
- ECP core size and compatibility with the stated oxidation/electron count;
- scalar relativistic or other relativistic treatment;
- functional/method and dispersion treatment;
- solvent and explicit-species model;
- integration grid and SCF controls;
- spin-state and wavefunction sensitivity plan; and
- geometry, frequency and final-energy level relationships.

Do not copy a Wang-group or other literature method as a default. `strict`
means additional evidence/sensitivity, not guaranteed accuracy, and remains
independent of `simple`, `general` or `complex` resources.

## 9. Future TS and frequency evidence

A later runtime extension must add metal-specific parsers and checks before a
candidate can be calculation-ready:

1. verify the requested electronic state before and after optimization;
2. verify coordination/hapticity/ligand inventory before and after;
3. require stationary-point and complete frequency evidence;
4. require exactly one raw imaginary frequency;
5. review whether the displacement follows the intended chemical coordinate;
6. reject modes dominated by unintended ligand, counterion or coordination
   loss unless that motion is the declared elementary step;
7. prevent cross-state checkpoint/Hessian reuse; and
8. define path evidence appropriate to single-surface, dissociative and
   spin-crossing cases.

The current `gaussian-ts-irc` path model remains unsupported for all metal
cases. Do not claim metal IRC connectivity from its main-group implementation.

## 10. Extension milestones

- `metal_m0_offline_design`: deterministic state/strategy/blocker/refusal
  artifact; implemented offline.
- `metal_m1_scientific_review`: one bounded real example with reviewed
  oxidation/electron count, spin, wavefunction, coordination, method and TS
  strategy; pending.
- `metal_m2a_candidate_audit_template`: candidate-bound atom-order,
  metal-center, coordination-contact, six-section and seed-strategy contract;
  implemented offline with execution refused.
- `metal_m2_offline_runtime_contract`: metal input audit, parser,
  wavefunction/coordination checks, fixtures and promotion rules; blocked.
- `metal_m3_execution_boundary`: separately reviewed execution design with
  exact scientific and live gates; blocked.
- `metal_m4_live_smoke`: small closed-shell single-reference metal TS smoke
  only after M1-M3 pass and receive explicit approval; blocked.

## 11. Refusal conditions

Keep submission refused when any of the following is unresolved:

- oxidation/electron count or ligand charge convention;
- credible multiplicity inventory or surface relationship;
- wavefunction/reference/stability policy;
- multireference concern;
- coordination, hapticity, ligand count or counterion model;
- method/basis/ECP/relativity review;
- elementary-step classification and atom map;
- TS seed-strategy evidence;
- metal-specific parser and structural/electronic post-checks; or
- execution-layer review.

Never interpret a detailed design artifact as calculation approval. Its value
is to make the missing scientific and software support explicit and testable.
