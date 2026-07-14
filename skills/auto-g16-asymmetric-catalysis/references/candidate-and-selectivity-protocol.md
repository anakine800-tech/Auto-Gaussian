# Candidate and selectivity protocol

Use this protocol to design or audit an asymmetric catalytic TS study. It is a
scientific data and review protocol, not a Gaussian route template.

## 1. Required study inputs

Do not generate candidates until all applicable fields are explicit:

- reaction identities, atom maps and reviewed stereochemistry;
- experimental product channels, temperature, solvent, additives and observed
  ee/dr/regioselectivity, including uncertainty when available;
- proposed elementary selectivity-determining step and its evidence;
- all reactant-side species and the common reference basin;
- catalyst-state hypotheses with charge, multiplicity and complete atom
  inventory;
- requested channels defined by product configuration and regioisomer;
- approved electronic-structure and thermochemistry protocol IDs; and
- candidate-space dimensions, expected levels and pruning rules.

If a paper proposes only a stereochemical drawing, record it as a model source,
not a TS structure.

## 2. Active-state matrix

### Chiral boron

Enumerate, when chemically relevant:

- catalyst-formation regioisomers and diastereomers;
- each inequivalent boron center and B(sp2)/B(sp3) coordination state;
- free, substrate-bound, base-bound, solvent-bound and product-bound forms;
- monodentate, chelating and cooperative dual-boron binding;
- substrate orientation at each site;
- hydride/borohydride, borate, borenium, neutral Lewis-acid and ion-pair models;
- catalyst scaffold conformers and aryl/fluoroaryl rotamers;
- aggregation, counterion, explicit additive and explicit solvent placement;
- catalyst/substrate complex versus separated-species reference models.

Do not assume the most easily drawn or crystallized adduct is the catalytically
relevant state.

### Metal with chiral ligand

Enumerate, when chemically relevant:

- precatalyst activation products and ligand stoichiometries;
- oxidation-state, charge and multiplicity hypotheses shown together;
- alternative spin states and any broken-symmetry concern;
- ligand conformers, rotamers, hemilabile coordination and hapticity;
- substrate coordination face, metal-fragment geometry and allyl/alkylidene
  configuration;
- counterion/contact-ion-pair/solvent placement;
- vacant-site, associated and dissociated forms; and
- distinct catalyst resting states that feed the stereodetermining step.

The current repository TS layer does not support transition-metal cases.
Retain the inventory for future development but set
`unsupported_requires_extension` and stop before calculation handoff.

## 3. Stereochemical channel matrix

Define channels chemically rather than as major/minor:

- product identifier and absolute/relative configuration;
- newly formed stereogenic centers, axes or helices;
- re/si, pro-R/pro-S, endo/exo or other applicable approach labels;
- regioisomer and catalyst-relative topicity;
- mapping from each TS to the product channel, with endpoint evidence when
  available.

Major/minor labels are analysis outputs. IRC forward/reverse labels are not
stereochemical labels.

## 4. Candidate generation and pruning

1. Generate the declared Cartesian product of active state, channel, binding
   mode, conformers, approach topology and optional ion-pair/additive/electronic
   state dimensions.
2. Preserve input stereochemistry and stable atom maps.
3. Prescreen only with an approved method. Store method, version, settings,
   score, rank and geometry hash. Prescreen energies are not DFT barriers.
4. Deduplicate using atom inventory, connectivity, stereochemistry, catalyst
   state, channel, atom map and geometry similarity.
5. Preserve every exclusion with reason, threshold and reviewer. A symmetry
   argument must include the reviewed atom mapping.
6. Promote immutable candidates with structure and manifest hashes. Promotion
   is not submission authorization.

High energy is a pruning reason only when the prescreen protocol and retention
window were approved before reviewing the result.

## 5. Comparison protocol and references

All candidates in a comparison group must share:

- chemical inventory or an explicit balanced thermodynamic cycle;
- catalyst-state/equilibrium model;
- optimization/frequency and single-point protocol;
- solvent model, temperature, standard state and concentration convention;
- low-frequency, symmetry and degeneracy conventions;
- reference basin and barrier formula; and
- validation and inclusion rules.

Do not compare a pre-reactive-complex barrier in one channel with a separated-
species barrier in another. Explicit solvent, counterions or additives change
the atom inventory and require balanced chemical potentials.

Build a method-sensitivity matrix when the predicted ordering is close or the
model is novel. A literature method is one candidate protocol, not an approval.

## 6. TS and path evidence

For every candidate record:

- optimization termination and stationary-point evidence;
- complete frequency data and the raw negative-frequency list;
- exactly one imaginary mode for a first-order saddle candidate;
- mode displacement images or vectors bound to the result hash;
- reviewer decision against the declared bond changes;
- a checkpoint-geometry audit bound to the exact TS input, log, result, mode
  review, accepted decision and checkpoint;
- a forward/reverse IRC plan bound to those same TS, decision and checkpoint
  hashes, with each direction mapped to the exact endpoint project;
- termination and structural identity of both endpoints; and
- failure/wrong-mode/duplicate/exclusion reasons.

Frequency count without displacement review is insufficient. IRC without
identified endpoints is insufficient. Endpoint `passed`, direction and
chemical-side labels are insufficient unless atom order, charge, multiplicity,
project and the hash-bound TS/IRC lineage all match the promoted candidate. A
failed candidate does not authorize an
automatic method, spin, geometry or chemistry change.

## 7. Ensemble aggregation

For an approved rapidly equilibrating conformer model:

```text
W_c = sum_i g_i exp[-(G_TS,i - G_ref)/(R T)]
G_eff,c^‡ = -R T ln(W_c)
```

For two channels define:

```text
DeltaDeltaG^‡ = G_eff,minor^‡ - G_eff,major^‡
major/minor = exp(DeltaDeltaG^‡/(R T))
ee = 100 * (major - minor)/(major + minor)
```

Use normalized populations for more than two channels. Use a kinetic network
instead of this expression when catalyst states are not rapidly equilibrating,
the selectivity-determining step is reversible, product channels interconvert,
or multiple steps contribute.

The current offline aggregation builder implements only
`boltzmann_ts_ensemble`. It rejects ledger-external candidates, changed
candidate artifacts, mismatched channels/states/protocols, non-finite energies
or temperatures, and non-positive degeneracies before calculating weights.

Always publish:

- included candidate IDs, energies and degeneracies;
- exclusions and coverage by dimension/channel;
- lowest-TS-only versus ensemble sensitivity;
- standard-state and low-frequency sensitivity;
- method sensitivity when available;
- unresolved candidates within the retention window; and
- whether one plausible missing candidate could reverse the ordering.

## 8. Interpretation analyses

Noncovalent-interaction, NBO, distortion/interaction or activation-strain
analyses may explain an ordering after the ensemble is established. Each needs
an approved fragmentation or population-analysis definition. None replaces TS
coverage, normal-mode review or path evidence.

Avoid causal wording based only on one optimized geometry. Prefer “consistent
with” unless controlled comparisons isolate the proposed interaction.

## 9. Stop and claim rules

Stop or downgrade when catalyst identity, atom inventory, stereochemistry,
charge/multiplicity, spin, reference state, method support, mode identity,
endpoint identity or candidate coverage is unresolved.

Use:

- `incomplete` for missing required evidence;
- `inconclusive` for conflicting evidence;
- `provisional` for a bounded but incomplete model; and
- `validated under the stated mechanism, protocol and coverage` only when all
  declared gates pass.

Never convert agreement with experimental ee into proof of a unique mechanism.

## 10. Implemented offline tooling and remaining priorities

The repository implementation now provides deterministic study normalization,
boron-center/coordination/binding/conformer/approach enumeration, logical and
same-channel geometry deduplication, candidate materialization with real-file
hashes, TS-result ingestion, Boltzmann aggregation, ee, and sensitivity
scenarios. It also produces a transition-metal support design while preserving
the runtime refusal.

Remaining scientific priorities are:

1. review reaction-specific active states and all candidate-space levels;
2. add chemistry-aware, stereochemistry-preserving complex construction above
   the current reviewed-XYZ materialization boundary;
3. add reviewed pruning decisions rather than automatic energy-window pruning;
4. benchmark alternative electronic-structure and thermochemistry protocols;
5. review the separate transition-metal extension gates without enabling it;
6. review the BF3-TS1 literature ledger and its unresolved neutral-singlet,
   route, solvent, thermochemistry, resource, and project fields; and
7. only after a new explicit approval, render and hash the final input in a
   fresh `/home/user100/SDL` project and consider one live execution. Keep
   BF3-TS2-B1/B2 gated on accepted BF3-TS1 mode evidence.
