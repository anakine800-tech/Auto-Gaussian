# Auto-G16 Asymmetric-Catalysis Module Design

Status: offline planning/audit Skill and design contract. No Gaussian input,
live submission, or reaction-specific computational protocol is authorized by
this document.

Module name: `auto-g16-asymmetric-catalysis`

## 1. Objective

Build an offline orchestration layer for transition-state studies in synthetic
organic asymmetric methodology, initially covering:

1. transition-metal catalysis with a chiral ligand; and
2. asymmetric catalysis by a chiral boron catalyst.

The module must answer a narrower and more auditable question than "find the
transition state":

> Given explicitly reviewed active-species and mechanism hypotheses, which
> stereochemical product channel is favored by a sufficiently covered,
> consistently computed ensemble of validated transition structures?

It organizes hypotheses and evidence. It does not discover the catalytic cycle
without human input, choose an electronic-structure protocol, or treat the
lowest TS found so far as proof that the search is complete.

## 2. Scientific conclusions and evidence levels

The module distinguishes four claims:

| Claim | Minimum evidence | Allowed wording |
| --- | --- | --- |
| located TS candidate | stationary point, complete frequency calculation, exactly one raw imaginary frequency | "first-order saddle candidate" |
| mode-reviewed TS | candidate plus accepted displacement along the intended coordinate | "mode-consistent TS" |
| path-validated TS | mode-reviewed TS plus reviewed forward/reverse path endpoints | "connects the reviewed sides" |
| selectivity model | consistently referenced TS ensembles for every compared channel plus documented coverage | "predicted selectivity under the stated model" |

A predicted selectivity is not a claim that the catalytic mechanism is unique.
If path validation is unavailable, including during any future metal pilot, the
result must remain `provisional` and state the missing evidence.

## 3. Why this is a separate module

`auto-g16-ts-irc` validates a reviewed TS family and its path. It currently
refuses transition-metal, broken-symmetry, excited-state, multireference,
periodic, and ONIOM workflows. That refusal is scientifically material and must
not be bypassed by an orchestration wrapper.

The new module owns a different layer:

- catalytic-cycle and active-species hypotheses;
- catalyst/substrate complex and conformer families;
- explicit stereochemical outcome channels;
- coverage and deduplication across competing TS families;
- common-reference thermochemistry and selectivity aggregation;
- uncertainty and claim-level reporting.

It delegates only supported, separately reviewed TS families to
`auto-g16-ts-irc`, visible structure/mode review to `auto-g16-view-rt-win`, and
approved transport/execution to `auto-g16-rtwin-pbs`.

## 4. Non-negotiable boundaries

- Keep all server work below `/home/user100/SDL`; use resolved, non-symlink,
  fresh, empty project directories and never overwrite or delete server data.
- A study/candidate/analysis JSON artifact is offline evidence and never a
  submission authorization.
- Do not infer functional, basis/ECP, dispersion, solvent, grid, SCF strategy,
  relativistic treatment, spin state, broken-symmetry state, TS algorithm, IRC
  settings, temperature, standard state, or low-frequency correction.
- Do not infer catalyst nuclearity, ligand count, counterion, protonation,
  aggregation, coordination state, resting state, or turnover-limiting step
  from a drawn precatalyst.
- Do not change chemistry, electronic state, or numerical method to rescue a
  failed candidate automatically.
- Never compare energies with different atom inventories or molecularities
  unless an explicit, balanced thermodynamic cycle and chemical potentials are
  part of the approved reference-state model.
- Never report a definitive ee/dr/regioselectivity from incomplete channel or
  conformer coverage.
- Preserve failed, duplicate, excluded, and unresolved candidates with reasons;
  do not erase them from the audit trail.

## 5. Study model

### 5.1 Chemical species and atom identity

Every catalyst, ligand, substrate, reagent, additive, counterion, explicit
solvent, intermediate, and product has a stable `species_id`, structure hash,
charge, multiplicity, formula, component count, atom count, and reviewed
stereochemical description. Atom maps must be explicit wherever structures are
compared across an elementary step.

An identity record is not interchangeable with a geometry. Multiple conformers
may share a species identity, while a change in protonation, coordination,
oxidation state, ligand count, or covalent connectivity creates a new state.

### 5.2 Catalyst-state hypotheses

Each `catalyst_state` is a reviewed chemical hypothesis with a complete atom
inventory. It records composition, total charge/multiplicity, nuclearity,
coordination, provenance, and why the state is included.

For a metal–chiral-ligand catalyst, also record:

- every metal element and atom index;
- formal oxidation-state assignment and whether it is experimentally known or
  a model assumption;
- ligand identities, count, denticity, hapticity, and coordination atoms;
- coordination geometry and labile sites;
- spin-state hypothesis and any alternative states that require comparison;
- counterion and ion-pairing model;
- whether the state is a precatalyst, resting state, on-cycle intermediate, or
  off-cycle hypothesis.

For a chiral boron catalyst, record each boron center separately:

- atom index and three- or four-coordinate state;
- local geometry and attached groups;
- Lewis-acid, Lewis-base-adduct, borate, or activated-catalyst interpretation;
- occupied and available substrate/additive binding sites;
- intramolecular or intermolecular bridging;
- counterion, protonation, aggregation, and explicit solvent/adduct model;
- reversible coordination or B(sp2)/B(sp3) interconversion relevant to the
  catalytic hypothesis.

Multi-boron catalysts must not be represented by a single generic "B active
site" label. Symmetry-equivalent centers may share an equivalence class only
after a reviewed atom mapping; a chiral environment may make nominally similar
centers diastereotopic.

### 5.3 Mechanism hypotheses

A `mechanism_hypothesis` defines one elementary stereochemistry-determining
step and its reference basin. It records:

- active catalyst state and all co-reactants;
- bond-forming, bond-breaking, and transferring atom pairs;
- expected reactant-side and product-side identities;
- whether the step is assumed reversible;
- evidence that the step controls enantio-, diastereo-, or regioselectivity;
- competing mechanisms included, excluded, or unresolved;
- any preceding equilibria required by the kinetic model.

The module does not require that the selectivity-determining step be the
turnover-limiting step, but it requires the distinction to be stated.

### 5.4 Stereochemical channels

A channel is a chemically defined outcome, not merely `major` or `minor`.
Record product identity, absolute/relative stereochemical descriptors, newly
formed stereogenic elements, substrate face (`re`, `si`, `pro-R`, `pro-S`, or
not applicable), regioisomer, and any catalyst-relative topicity.

`major` and `minor` labels are assigned only after aggregation. Forward/reverse
IRC labels are never used as product labels without endpoint identification.

## 6. Candidate-space decomposition

One candidate is the Cartesian realization of a tuple:

```text
mechanism
× active catalyst state
× stereochemical channel
× substrate/catalyst binding mode
× catalyst conformer
× substrate conformer
× approach topology / ligand rotamer / ion-pair placement
× electronic-state hypothesis
× explicit-solvent or additive placement (when approved)
```

The study manifest declares which dimensions are applicable and the expected
levels for each. Generation tools may enumerate Cartesian products, but only a
chemical review can prune them. Every exclusion needs a reason and reviewer;
"high energy" is valid only when the prescreen protocol and threshold are
recorded.

### Candidate generation phases

1. **Define state space.** Review species, catalyst states, mechanisms,
   channels, and atom maps.
2. **Generate complexes.** Build binding modes and approach topologies without
   losing catalyst or substrate stereochemistry.
3. **Prescreen conformers.** Use an explicitly approved method. Force-field or
   semiempirical values are rankings only and never Gaussian barriers.
4. **Deduplicate.** Use composition, connectivity, stereochemistry, catalyst
   state, channel, atom map, and geometry similarity. Mirror-related candidates
   are not duplicates in a chiral catalyst environment.
5. **Promote candidates.** Record immutable geometry and manifest hashes plus a
   review decision. Promotion does not authorize submission.
6. **Run TS evidence workflow.** Only after exact scientific and live approval,
   and only through a scientific layer that supports the chemistry.
7. **Reopen coverage.** A failed candidate, new coordination state, or newly
   found lower conformer may require additional candidates; it never triggers
   an automatic changed-chemistry retry.

The implemented version separates enumeration from materialization. The
candidate-space ledger records retained, excluded and logically equivalent
tuples before a geometry exists. Candidate JSON is created only after a real
local XYZ and atom map are supplied and hashed. Geometry deduplication uses an
ordered atom-pair distance fingerprint, is restricted to the same catalyst
state and stereochemical channel, and automatically rejects rather than
promotes a duplicate.

## 7. Metal-specific design

Metal systems add electronic-state and coordination uncertainties that are not
present in ordinary closed-shell main-group TS searches.

### Required offline gates

- The element-specific basis/ECP and relativistic model are explicit.
- Formal oxidation state, d-electron interpretation, total charge, and
  multiplicity are shown together; none is inferred from the others.
- Alternative spin states are either included or explicitly excluded with
  scientific rationale.
- Ligand dissociation/association, counterion binding, and substrate
  coordination alternatives are represented as distinct catalyst states.
- Atom maps preserve hapticity and metal–ligand coordination annotations even
  when covalent-bond perception is unreliable.
- A broken-symmetry or multireference concern stops promotion until a future
  supported protocol exists.

### Runtime boundary

Version 1 of this design produces metal candidates with
`support_status: unsupported_transition_metal` and
`calculation_ready: false`. A later transition-metal extension must define its
own input audit, wavefunction/state checks, mode interpretation, and path
validation before these values may change.

The current `design-metal-support` command emits a separate hash-bound checklist
for oxidation/electron count, spin-state space, wavefunction stability and spin
contamination, coordination/hapticity/counterions, and method/basis/ECP/
relativity review. It also creates one mechanism-bound TS-search family per
declared elementary step with three unselected design candidates:

- Hessian-guided single-guess search;
- endpoint-bound QST2/QST3; and
- reviewed relaxed-coordinate scanning followed by a separately reviewed TS
  seed.

The builder does not select among them. Each family is bound to an explicit
electronic state, stereochemical channel set, forming/breaking/transfer
coordinates and a reaction-surface hypothesis. Unknown elementary-step class,
oxidation-state change, spin crossover, coordination change or surface model
is a blocker, not an inference.

`build-metal-ts-audit-template` then binds one unsupported metal candidate to
the exact support-design and candidate SHA-256 values. It freezes the one-based
atom order, metal-center identities, intended coordinate, candidate
coordination contacts and complete unselected strategy inventory. Its six
audit sections separately block electron accounting, spin/surface,
wavefunction, coordination, method protocol and TS/path acceptance. It leaves
d-electron counts and coordination distance windows unset and cannot render an
input.

The versioned extension milestones are:

1. `M0`: deterministic offline state/search design and refusal audit;
2. `M1-contract`: candidate-bound scientific-review source/output schemas,
   builder, validator, dry run and refusal tests;
3. `M1`: real scientific review of oxidation states, electron counts, spin
   surfaces, wavefunctions, coordination states and mechanism families;
4. `M2a`: candidate-bound offline atom/state/coordination audit template;
5. `M2b`: candidate-bound, observation-only log parser with unconditional
   scientific-acceptance and promotion refusal;
6. `M2c`: candidate/template/M1-bound read-only observation of an existing
   single-step Cartesian Gaussian input, with no rendering, protocol selection
   or input acceptance;
7. `M2d`: four-section manual wavefunction, coordination, mode and input-
   acceptance decision sidecar, with no top-level authority;
8. `M2`: runtime/promotion contracts beyond the M2b/M2c observers and M2d
   decision record;
9. `M3`: malformed, wrong-state, wrong-coordination, spin and wavefunction
   failure fixtures; and
10. `M4`: a separately approved exact live smoke test.

`M0`, `M1-contract`, `M2a`, `M2b`, `M2c` and the M2d decision contract are
implemented offline. The real M1/M2 scientific example remains pending.
Scientific acceptance is never granted; promotion and submission remain
refused, including when all four synthetic M2d sections are accepted.

## 8. Chiral-boron-specific design

The boron path must support chiral Lewis acids, oxazaborolidine-like catalysts,
chiral boranes/borenium or borate hypotheses, and multi-boron Lewis acids
without treating them as one mechanism.

Required competing hypotheses may include, as applicable:

- free catalyst versus substrate-bound or reagent-bound catalyst;
- monodentate versus chelating substrate coordination;
- binding at inequivalent boron centers;
- three-coordinate Lewis acid versus four-coordinate adduct/borate;
- intramolecular versus intermolecular activation;
- catalyst aggregation or cooperative dual-site binding;
- counterion/contact-ion-pair and explicit additive/solvent participation;
- chair/boat or endo/exo approach families;
- reversible boron coordination or bond migration before the stereogenic step.

The module may handle a supported closed-shell main-group candidate through the
existing TS layer only after charge, multiplicity, atom order, mode, routes, and
endpoints satisfy that layer's gates. A boron catalyst is not automatically
simple merely because it contains no transition metal.

## 9. Protocol and reference-state matrix

Each study carries immutable protocol IDs rather than copying free-form routes
into candidates. A protocol set records separately:

- geometry/TS optimization route;
- frequency route;
- forward and reverse IRC routes when supported;
- endpoint Opt/Freq routes;
- single-point route;
- basis/ECP by element and any relativistic treatment;
- dispersion, solvent, grid, SCF, and optimization settings;
- temperature, pressure/standard state, concentration model, symmetry number,
  and low-frequency policy;
- resource tier and expected stage count.

The reference-state model states the complete formula for each barrier. For
example, a catalyst–substrate complex TS may be compared to the corresponding
pre-reactive complex, or to separated catalyst and substrates with an approved
standard-state treatment. Mixing those definitions inside one comparison group
is forbidden.

Species counts matter. Association reactions, ion pairs, explicit solvent,
counterions, and additives require consistent chemical potentials and
standard-state corrections. An apparently lower TS with an extra molecule is
not comparable until the reference cycle accounts for that molecule.

## 10. TS validation and handoff

For every promoted candidate:

1. audit the exact Cartesian structure, stereochemistry, atom map, charge,
   multiplicity, protocol, resources, project name, and hashes;
2. obtain explicit live approval before any submission;
3. require stationary-point and complete frequency evidence;
4. require exactly one raw negative frequency, with no automatic numerical
   tolerance;
5. review the displacement against the declared forming/breaking/transferring
   coordinates and catalyst/substrate motion;
6. preserve a separate immutable decision bound to result/review hashes;
7. run both IRC directions only after their own approved plans and only when the
   scientific layer supports the system;
8. identify endpoints and distinguish connected complexes from dissociated
   fragments;
9. do not automatically retry a failed search or path.

Candidates with the wrong mode may be scientifically useful diagnostics, but
they are excluded from selectivity aggregation.

## 11. Ensemble thermochemistry and selectivity

### 11.1 Comparability gate

All members of one comparison group must share:

- chemical inventory or an explicitly balanced reference cycle;
- catalyst state/equilibrium model;
- protocol stack and solvation model;
- temperature, standard state, low-frequency policy, and energy units;
- validation threshold and product-channel definition.

If any item differs, the analysis is `blocked_incomparable` rather than a mixed
energy table.

### 11.2 Within-channel aggregation

The default research design is ensemble aggregation, not "one lowest structure
per enantiomer." For rapidly equilibrating conformers under an approved
Curtin–Hammett/TST model, channel weights are summed:

```text
W(channel) = sum_i degeneracy_i * exp[-(G_TS,i - G_reference)/(R*T)]
G_eff‡(channel) = -R*T*ln(W(channel))
```

All terms must use the same energy zero and standard state. The module records
the exact formula, degeneracy convention, included candidates, exclusions, and
unit constants. A `lowest_ts_only` calculation is allowed only as a labeled
sensitivity analysis, not the default validated model.

If catalyst states do not rapidly equilibrate, if steps are reversible, if
product interconversion occurs, or if several steps control selectivity, use an
explicit kinetic-network model. The simple two-channel equation is then
insufficient.

### 11.3 Two-channel selectivity

Define the sign convention explicitly:

```text
ΔΔG‡ = G_eff‡(minor) - G_eff‡(major)   # positive when major is favored
major/minor = exp(ΔΔG‡ / R*T)
ee_percent = 100 * (major - minor) / (major + minor)
```

For more than two stereoisomeric or regioisomeric channels, report normalized
channel populations and derive ee/dr only for an explicitly selected grouping.
Do not force a multi-channel result into a binary formula.

### 11.4 Uncertainty and sensitivity

Report at minimum:

- conformer/coordination-state coverage;
- electronic-structure protocol sensitivity when available;
- low-frequency and standard-state sensitivity;
- numerical convergence and duplicate-family sensitivity;
- the energy gap from each channel minimum to its highest retained candidate;
- whether adding one plausible missing candidate could reverse the prediction.

Distortion/interaction or activation-strain analysis may be attached as an
interpretive artifact. It is not a substitute for TS coverage or validation and
must use an explicitly defined fragmentation scheme.

## 12. Coverage semantics

Every applicable candidate-space dimension has:

- `expected_levels`;
- `observed_levels`;
- candidate counts by channel;
- exclusions with rationale;
- `coverage_status`: `complete`, `reviewed_pruned`, `incomplete`, or `unknown`.

A comparison may be `provisional` with `reviewed_pruned` coverage, but
`validated` requires every dimension to be `complete` or `reviewed_pruned`, no
unresolved candidate below the approved retention window, and at least one
included, mode-reviewed TS per requested channel. Path validation requirements
are declared separately and cannot be silently weakened.

The contract intentionally has no percentage-complete field: candidate spaces
are not known well enough for a precise percentage unless all levels were
enumerated in advance.

## 13. State machine and gates

```text
draft study
  -> G0 chemical-space review
reviewed study
  -> generate / prescreen / deduplicate
candidate inventory
  -> G1 candidate promotion
promoted offline candidates
  -> G2 exact scientific + live approval per job
TS/Freq evidence
  -> G3 mode decision
mode-reviewed candidates
  -> G4 separately approved IRC/path evidence (when supported)
comparable channel ensembles
  -> G5 coverage + aggregation review
provisional | validated | incomplete | inconclusive
```

- **G0:** species, stereochemistry, catalyst states, mechanism hypotheses,
  channels, atom maps, protocol IDs, reference states, and candidate dimensions.
- **G1:** exact candidate geometry/hash, binding mode, conformer provenance,
  charge/multiplicity/electronic state, method support, and deduplication.
- **G2:** exact route, resources, fresh SDL project, input hash, and explicit
  submission approval. This gate is outside the offline contract.
- **G3:** exactly one imaginary mode and accepted reaction-coordinate review.
- **G4:** direction-specific, separately approved path and endpoint evidence;
  required for path-validated claims.
- **G5:** common reference, complete/reviewed-pruned coverage, inclusion rules,
  aggregation model, uncertainty, and final claim wording.

## 14. Failure and stop semantics

Stop or downgrade the claim when any of these occurs:

- catalyst identity/state, atom inventory, stereochemistry, charge,
  multiplicity, oxidation state, or spin hypothesis is unresolved;
- a requested catalyst class is unsupported by the scientific layer;
- TS optimization/frequency fails or the mode count is not exactly one;
- the imaginary mode is wrong, ambiguous, or unreviewed;
- path endpoints are absent or inconsistent with the declared step;
- channels use different protocol/reference-state/standard-state policies;
- a candidate has a different stoichiometry without a balanced cycle;
- conformer, binding-mode, coordination-state, or electronic-state coverage is
  incomplete or unknown;
- both channels collapse to the same structure unexpectedly;
- the predicted ordering is within an unresolved sensitivity range;
- a duplicate or enantiomer relationship cannot be decided safely.

Use `failed` for a definite failed artifact, `incomplete` for missing required
evidence, `inconclusive` for conflicting evidence, `provisional` for a clearly
bounded model, and `validated` only within the stated mechanism and coverage.

## 15. Offline artifacts

The implemented contract consists of:

- `gaussian-asymmetric-catalysis-study/1` — immutable scope, state space,
  protocols, comparison groups, and gates;
- `gaussian-asymmetric-ts-candidate/1` — one promoted or proposed candidate;
- `gaussian-asymmetric-ts-result/1` — parsed and reviewed TS evidence;
- `gaussian-asymmetric-selectivity-analysis/1` — coverage, aggregation,
  uncertainty, and claim.
- `gaussian-asymmetric-candidate-space-spec/1` and
  `gaussian-asymmetric-candidate-ledger/1` — deterministic enumeration and
  deduplication history;
- `gaussian-asymmetric-materializations/1` and
  `gaussian-asymmetric-energy-record/1` — explicit geometry and comparison-
  energy inputs;
- `gaussian-asymmetric-metal-support-design/1` — refusal-preserving metal
  scientific design;
- `gaussian-asymmetric-metal-ts-audit-template/1` — candidate-bound blocked
  electron/spin/wavefunction/coordination/method/TS audit contract;
- `gaussian-asymmetric-metal-scientific-review-source/1` — reviewer-supplied,
  exact-lineage M1 values and closed evidence locators;
- `gaussian-asymmetric-metal-scientific-review/1` — candidate-bound M1 sidecar
  with no scientific acceptance, promotion, input or execution authority;
- `gaussian-asymmetric-metal-input-observation/1` — candidate/template/M1-
  bound read-only facts from an existing single-step Cartesian Gaussian input;
  route and identity matching grant no protocol, input or execution approval;
- `gaussian-asymmetric-metal-result-observation/1` — candidate-bound read-only
  terminal/frequency/`S**2`/stability-text/coordination-distance facts with no
  TS, promotion, selectivity or execution claim; and
- `gaussian-asymmetric-metal-acceptance-review-source/1` and
  `gaussian-asymmetric-metal-acceptance-review/1` — reviewer-authored and
  candidate-bound four-section M2 decision records with no top-level
  acceptance, promotion or execution authority; and
- `gaussian-asymmetric-literature-benchmark-ledger/1` — reviewed literature
  coordinates, exact hashes, identities, expected observables, and unresolved
  approval gates; and
- `gaussian-asymmetric-smoke-proposal/1` — priority-1, non-runnable closed-
  shell main-group proposal. It contains no input while protocol fields remain
  unresolved; and
- `gaussian-asymmetric-live-smoke-evidence/1` — sanitized post-run evidence
  bound to the exact approval, input, job record, parsed TS result, mode review,
  and mode decision. It contains no job ID, server path, log, or checkpoint and
  grants no authority for another action.

Schemas provide structural validation. The semantic validator additionally
checks cross-artifact IDs, hashes, channel membership, no-submission flags,
method support, common comparison policy, and claim gates. Schemas and examples
cannot authorize a live job.

## 16. Implementation status and remaining sequence

Implemented offline: deterministic study normalization; boron center,
coordination, binding, conformer and approach enumeration; logical and
same-channel geometry deduplication; real-file candidate hashing; TS evidence
ingestion; log-sum-exp ensemble aggregation; ee and sensitivity scenarios;
transition-metal state/search-family design with explicit oxidation/electron,
spin, wavefunction, coordination and method review blocks, three unselected TS
strategy candidates, candidate-bound metal TS audit templates, an M1 review
sidecar, M2b observation-only metal log parser, M2c existing-input observer,
M2d four-section manual-decision sidecar, extension milestones and enforced
refusal; and a precise
BF3-TS1/BF3-TS2-B1/B2 literature ledger plus a
historical BF3-TS1 evidence chain and an in-flight BF3-TS2-B1 lineage.

Remaining work is scientific review rather than live execution:

1. use the implemented M1 sidecar contract to review a real candidate's
   oxidation/electron accounting, spin surfaces, wavefunction, coordination,
   method evidence and TS-design candidate without inferring missing values;
2. keep `metal_m1_scientific_review` pending until that real review is field-
   complete; record completeness still grants no scientific acceptance;
3. use the implemented M2a template, M2b/M2c observers and M2d manual-decision
   sidecar for one real bounded review while preparing M3 runtime/promotion and
   adversarial execution-boundary fixtures; M2d section decisions grant no
   live authority;
4. independently accept or reject BF3-TS2-B1 from stable terminal evidence,
   exactly one imaginary frequency and manual C13–C21 mode review;
5. decide on BF3-TS2-B2 only after that B1 decision; and
6. resume chemistry-aware chiral-boron construction and broader enumeration
   work after the transition-metal design milestone.

## 17. Wang-group literature audit and design consequences

The first literature audit focused on Xiao-Chen Wang group papers relevant to
chiral bisboranes, pyridine functionalization, borane/transition-metal
cooperative catalysis, and mechanistic transition-state calculations. Exact
paper-by-paper evidence is maintained in
`skills/auto-g16-asymmetric-catalysis/references/wang-group-computational-precedents.md`.

The audit changes the implementation plan in five ways:

1. **Do not define a group-wide DFT default.** Verified papers use materially
   different Gaussian versions, functionals, basis stacks, solvation models,
   temperatures, and low-frequency treatments. Literature methods belong in a
   benchmark matrix and require reaction-specific approval.
2. **Separate the question being calculated.** Earlier calculations often
   address mechanism, regioselectivity, site selectivity, or Lewis-acid
   coordination without calculating the experimental enantioselectivity.
   Artifact metadata must name the exact claim supported.
3. **Preserve experimental stereochemical evidence.** Crystal structures,
   nonlinear effects, matched/mismatched experiments, kinetic resolution, and
   stereochemical models remain distinct evidence types. A drawn model is not
   converted into a TS result.
4. **Add candidate-space provenance.** Even the 2025 borane/chiral-Ni example,
   which reports six stereodetermining TSs, does not publish a systematic
   machine-readable ledger of catalyst states, conformers, binding modes,
   exclusions, failures, and ensemble weights. The module must supply this
   missing audit layer.
5. **Treat metal support as new scientific work.** The literature demonstrates
   the relevance of a full metal-ligand-borane TS, but it does not remove the
   repository's current transition-metal refusal. Wavefunction/state audits,
   spin/coordination handling, path validation, and failure tests remain a
   separate extension.

The resulting Skill is intentionally an offline planner, deterministic builder,
and auditor. It contains no Gaussian execution builder, submission command, or
automatic research-method selection.

## 18. Design references

- Gaussian, *GaussView 6 Help*, transition-structure optimization and QST2/QST3:
  <https://gaussian.com/wp-content/uploads/dl/gv6.pdf>
- Bickelhaupt and Houk, "Analyzing Reaction Rates with the
  Distortion/Interaction–Activation Strain Model," *Angew. Chem. Int. Ed.* 2017,
  DOI: <https://doi.org/10.1002/anie.201701486>.
- Paton, Goodman, and Pellegrinet, "Mechanistic Insights into the Catalytic
  Asymmetric Allylboration of Ketones," *Org. Lett.* 2009, DOI:
  <https://doi.org/10.1021/ol802270u>.
- Yang et al., "Construction of C–B axial chirality via dynamic kinetic
  asymmetric cross-coupling mediated by tetracoordinate boron," *Nat. Commun.*
  2023, DOI: <https://doi.org/10.1038/s41467-023-40164-6>.
- Kolakowski and Williams, "Stereoinduction by distortional asymmetry,"
  *Nat. Chem.* 2010, DOI: <https://doi.org/10.1038/nchem.577>.

These sources motivate explicit active-species hypotheses, competing TS
topologies, B(sp2)/B(sp3) states, and distortion/interaction interpretation.
They do not define a universal computational method for a new reaction.
