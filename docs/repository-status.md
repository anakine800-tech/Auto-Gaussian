# Auto-G16 Repository Status

Status date: 2026-07-15

Stable release branch: `main`. New work uses short-lived `codex/` feature
branches and is integrated through reviewed pull requests with required checks.

Auto-G16 2.1.0 was released on 2026-07-14. It contains the W1 reaction-intake
and reaction-literature capability added after `v2.0.1`. Auto-G16 2.2.0
contains the post-2.1 W2 knowledge base, W3 offline
mechanism-network slice, release/dependency/security hardening, and the
transition-metal offline preview contracts described below. Publication of
the verified `v2.2.0` tag and GitHub Release was authorized on 2026-07-15.

All nine repository-owned Skill folders and machine names now use the
`auto-g16-` prefix, and all nine human-facing display names begin with
`Auto-G16`. Repository source remains authoritative. Release deployment must
run `scripts/check_skill_sync.py`, review the exact named-Skill diffs, and
synchronize only the validated release copies; a GitHub checkout never implies
that a machine-local deployment is current. The namespace remains mandatory
for future project Skills; versioned scientific schemas and immutable
historical records retain their identifiers.

The v2.1.0 release deployment covered the eight Skills in that tag. The current
repository contains nine Skills. Machine-local deployments are deliberately
not treated as repository state: each named Skill must be validated, diffed
and synchronized independently from `skills/`. Deployment never authorizes a
live test or calculation.

The 2.2.0 release's W2B-2 line is covered by the current offline suite,
including immutable-record validation, deterministic store/index rebuilds,
permission-negative queries, reviewed import/export, redaction, snapshot
binding and the GaussView Unicode-path regression. It grants no network,
Gaussian, PBS or calculation authority.

The merged transition-metal preview adds the candidate-bound M1 review sidecar
contract and M2b observation-only metal parser, an M2c read-only observer for
existing Gaussian inputs and an M2d four-section manual acceptance-decision
sidecar. The exact `auto-g16-asymmetric-catalysis` named Skill was synchronized
and its explicitly approved deployed-copy offline smoke passed while retaining
`unsupported_requires_extension`, refused submission, `calculation_ready:
false`, and `live_actions: false`. This is not metal runtime support or
scientific acceptance.

The target architecture is specified in
`docs/end-to-end-reaction-computation-workflow.md`. It defines the implemented
offline reusable-knowledge foundation and the remaining literature TS-
precedent, mechanism-network, calculation-DAG, free-energy/kinetic and final-
report layers needed to progress from W1 to an auditable whole-reaction study.

## Current capability

The version-controlled source under `skills/` currently provides:

- ChemDraw structure reconstruction and explicit stereochemical review;
- strict whole-scheme transcription, source-exact/normalized conditions and
  editable reaction-package artifacts recovered into repository source;
- audited ChemDraw/SMILES-to-Cartesian conversion;
- conformer preparation and visible GaussView handoff on RTwin;
- guarded Gaussian 16 transport through RTwin to PBS, including immutable
  hashes, fresh-project enforcement, monitoring, fetch, result parsing, and
  repeated-evidence terminal scheduler-zombie cleanup;
- an offline TS–Freq–IRC scientific layer with single-guess and QST family
  audits, hash-bound terminal-result intake, exactly-one-imaginary-mode review,
  checkpoint-bound AllCheck continuations, separately approved IRC directions,
  and connected or reviewed fragmented endpoint evidence;
- a literature-grounded, offline asymmetric-catalysis planning/audit Skill for
  active-state hypotheses, candidate-space coverage, comparable TS ensembles,
  and bounded selectivity claims; and
- an integrated offline top-level intake adapter with hash-bound reaction
  intake, species registry, balance review and condition-to-model artifacts;
- an offline-first reaction-literature Skill with reviewed query planning,
  Crossref/OpenAlex metadata retrieval, raw-response hashes, DOI deduplication,
  transparent lexical screening, source-located evidence templates and fail-
  closed evidence validation; and
- the W2A `auto-g16-knowledge-base` Skill with five closed immutable-record
  contracts, strict canonical-hash validation, identity/state/geometry
  separation, complete reported-method/source-anchor rules, typed links,
  immutable snapshot membership and duplicate/conflict audit reporting; and
- its W2B-1 canonical record/object layout, content-address verification,
  deterministic SQLite migration/rebuild, stale-index refusal, exact offline
  permission-filtered query and snapshot dependency verification; and
- its W2B-2 hash-bound plan-review-apply import, lawful-object ingestion,
  dependency-aware redacted/full JSON export and transfer manifests.

The W1 builder assigns stable step/occurrence/condition IDs, binds every drawn
reactant/product exactly once, refuses missing condition decisions, preserves
source-exact values, records blockers and never produces a calculation-ready
or submission-authorizing artifact. It does not yet create a mechanism,
reference basin, candidate geometry, protocol or calculation DAG.

The repository now provides the W2A portable record layer for reviewed
catalyst/ligand identities, represented states, geometries, complete
computational methods, papers/SI/books, typed links and immutable per-study
snapshots. W2B-1 adds canonical record/object verification, deterministic
SQLite migrations/rebuild/query and declared offline-principal filtering.
W2B-2 adds exact plan-review-apply import, lawful content-addressed-object
ingestion, `no_export` exclusion, metadata-redacted/full JSON export and
dependency-aware downgrade. It still lacks authentication, signatures,
durable audit logging, binary export and chemical search. Offline access checks
are not a filesystem or multi-user security boundary. The W2 design and remaining stages
are recorded in `skills/auto-g16-reaction-workflow/references/knowledge-database-design.md`.

The repository now provides reproducible metadata discovery and source-evidence
review scaffolding, but not automatic lawful full-text/SI extraction,
mechanism-support matrices, source-to-target atom correspondence, or reviewed
target TS-seed proposals. The existing BF3 and asymmetric-catalysis records
remain fixed precedents rather than automatic target-mechanism proof. The full
W2 contract and remaining stages are recorded in
`skills/auto-g16-reaction-workflow/references/literature-evidence-design.md`.

The TS–Freq–IRC feature and its endpoint workflow have been merged to `main`.
The repository contains tracked live-smoke evidence for the endpoint workflow
and for scheduler-zombie cleanup. Those records are historical evidence only;
they do not authorize another live calculation.

## Work completed in this feature line

This feature line established the design, offline data boundary, literature
record, and planning/audit Skill for `auto-g16-asymmetric-catalysis`. The intended
scientific scope is method-development work involving:

1. transition-metal catalysts bearing chiral ligands; and
2. chiral boron catalysts, including Lewis-acid/base adduct and coordination-
   state alternatives.

The current Skill is an offline orchestrator and deterministic builder for
reaction hypotheses, catalyst states, stereochemical channels, TS conformer
families, evidence coverage, and selectivity aggregation. It is not a universal
TS generator and it will not
choose a research method, basis/ECP, solvent, spin state, TS algorithm, IRC
settings, or low-frequency treatment.

The current development priority is the transition-metal TS capability design.
Version 1 now materializes deterministic state audits and mechanism-bound
search families, candidate-bound M1 review records, candidate-bound audit
templates, an observation-only metal log parser and a read-only existing-input
observer plus separate wavefunction/coordination/mode/input decision records
while retaining unconditional top-level scientific/input/mode acceptance,
promotion and execution refusal. Further chiral-boron capability work is
deliberately sequenced after this milestone.

## Deliberate limitations

- The `auto-g16-asymmetric-catalysis` Skill is runnable only as an offline
  planning, deterministic-building, ingestion, and audit workflow. It has no
  Gaussian execution builder or live submission path,
  transition-metal calculation support, or automatic method selection.
  Its metal parser records only hash-bound log observations and cannot accept a
  TS, electronic state, coordination state, method or selectivity claim.
  Its M2c parser reads only an existing single-step Cartesian input; route,
  identity and task-keyword observations cannot select a protocol, accept an
  input or validate a server path.
  Its M2d sidecar records four explicit human decisions, but even four bounded
  accepted sections cannot promote a candidate or authorize a calculation.
  Its M1 sidecar records reviewer-supplied values but never grants scientific
  acceptance; the complete synthetic fixture does not satisfy the real M1
  milestone.
- The current `auto-g16-ts-irc` Skill explicitly refuses transition-metal,
  broken-symmetry, excited-state, multireference, periodic, and ONIOM jobs.
  The new design preserves that refusal. Metal support needs a separately
  reviewed scientific extension before any candidate can become calculation-
  ready.
- A chiral catalyst structure by itself does not define the active catalyst.
  Ligand count, counterion, additive, protonation, aggregation, coordination
  geometry, substrate binding mode, boron coordination number, and solvent
  participation remain explicit hypotheses.
- A single major/minor TS pair is not adequate coverage unless a review records
  why all other thermally and mechanistically relevant families were excluded.
- A computed energy difference is not reportable as a validated ee when the
  comparison uses inconsistent stoichiometry/reference states, incomplete
  conformer coverage, unreviewed modes, or mixed thermochemical policies.

## Offline artifacts added by the design phase

- `docs/asymmetric-catalysis-design.md`: module boundaries, scientific model,
  candidate-generation graph, approval gates, aggregation rules, failure
  semantics, and implementation sequence.
- `docs/asymmetric-catalysis-offline-contract.md`: normative semantic rules for
  the versioned JSON artifacts.
- `docs/asymmetric-catalysis-v1-readiness.md`: non-authorizing merge gates,
  named-Skill deployment plan, B1 terminal acceptance checklist, and post-v1
  priority order.
- `docs/asymmetric-catalysis-smoke-proposal.json`: exact closed-shell main-group
  BF3-TS1 literature proposal bound to the reviewed coordinate ledger. Missing
  route, solvent, charge/multiplicity approval, resources, and project fields
  remain unresolved, so no Gaussian input is rendered.
- `studies/wang_2024_bf3_ts/`: BF3-TS1 and BF3-TS2-B1/B2 SI coordinates,
  identities, exact hashes, geometry fingerprints, reaction-coordinate maps,
  reported target values, scientific gates, and the deterministic aggregate
  ledger. It now also contains a separate workflow-status ledger, sanitized
  accepted BF3-TS1 `r01` evidence, and the selected/audited BF3-TS2-B1
  `standard` input lineage. The exact B1 input received separate live approval
  and completed normally in 28 optimization steps and 29 SCF calculations. Its
  228 modes contain the sole -389.3384 cm⁻¹ imaginary frequency, and its
  hash-bound C13–C21 animation decision is accepted. Separately approved B1
  bidirectional IRC work remains endpoint-incomplete; each direction now has a
  project/input-hash-bound offline terminal-intake template that stops before
  chemical-side assignment. B2 now has a B1-matched
  standard offline input candidate, exact coordinate/route/hash audits and a
  precommitted terminal acceptance plan plus an offline intake template that
  stops at manual C13–C21 mode review. That exact B2 input subsequently
  received one-time live approval and is queued; no retry or replacement is
  authorized. Operational job files remain local and ignored. Full BCF
  TS1/TS2-B1 remain deferred 87/108-atom benchmarks.
- `studies/wang_2024_cat2_alpha_alkylation/`: a real-reaction offline forward
  study that records the reported CAT2 reaction, conditions and selectivity,
  while leaving the unresolved active state, charge/multiplicity, structures,
  atom maps, stereochemical face mapping, candidate coverage and protocol
  explicitly blocked. The linked BF3 ledger remains an achiral mechanistic
  submodel and is not treated as a CAT2 geometry or ee ensemble.
- `contracts/asymmetric-catalysis/*.schema.json`: Draft 2020-12 schemas for the
  study, candidate space, ledger, materializations, candidate, energy record,
  result, analysis, metal-support design, candidate-bound metal TS audit
  template, M1 scientific-review source and sidecar, observation-only metal
  result record, literature benchmark, and smoke proposal, plus a sanitized
  live-smoke evidence record that binds the exact
  approval/input/job/TS/mode chain without retaining a job ID, server path,
  Gaussian log, or checkpoint.
- `tests/fixtures/asymmetric_catalysis/`: non-runnable metal and chiral-boron
  examples, including complete/incomplete M1 review-source records and
  synthetic success/incomplete metal logs used only by offline contracts.
- `scripts/validate_asymmetric_contract.py`: standard-library-only offline
  structural and cross-artifact semantic validator.
- `skills/auto-g16-asymmetric-catalysis/`: offline workflow plus a verified
  Wang-group computational-precedent audit and a candidate/selectivity
  protocol, transition-metal strategy-evidence matrix, deterministic builder,
  support design, M1 review sidecar and observation-only metal result audit.
  Publisher PDFs are not stored in the repository.

All design-phase artifacts set or imply `calculation_ready: false` and
`no_submission_authorization: true`. They perform no SSH, PBS, Gaussian,
deployment, cancellation, or server cleanup operation.

## Offline validation snapshot

On 2026-07-15, this feature branch passed 142 offline tests. In particular:

- all sixteen artifact types passed the repository's fail-closed Draft 2020-12
  schema subset validator; unknown schema keywords are refused until the
  validator and tests are extended;
- strict JSON loading rejected duplicate keys and non-standard `NaN` or
  infinite numeric constants;
- the complete synthetic chiral-boron study/candidate/result/analysis hash chain
  passed the offline semantic validator;
- deterministic boron-space enumeration retained channel identity, recorded
  logical duplicates, and rejected same-channel geometry duplicates;
- TS ingestion, Boltzmann aggregation, ee, lowest-TS-only and adversarial
  energy sensitivity passed synthetic end-to-end tests;
- result ingestion required a promoted offline candidate, and path validation
  bound the same TS, mode decision, checkpoint audit, IRC plan, atom order,
  charge/multiplicity, direction-specific project and both endpoint audits;
- aggregation rejected tampered or ledger-external results, rebound each result
  to its materialized candidate artifact, and refused unsupported aggregation
  models or non-finite thermochemical inputs;
- the synthetic metal candidate passed only in the mandatory
  `unsupported_transition_metal` state;
- M1 scope labels were bound to their allowed evidence-source types, and M2d
  real scope was refused without a real non-synthetic M1, named reviewer,
  valid calendar date and exclusively non-synthetic decision evidence;
- the metal-support design reproduced the study's explicit oxidation-state
  hypotheses without inferring d-electron counts, bound each mechanism to
  three unselected TS-search strategies, exposed spin/wavefunction/
  coordination/method blockers, recorded extension milestones, and retained an
  unconditional submission refusal. The candidate-bound template additionally
  freezes the atom order, metal-center identities, intended coordinate,
  coordination contacts and all three unselected seed strategies while keeping
  six scientific audit sections blocked. The M2b parser additionally bound a
  synthetic local log to the exact candidate/template hashes, parsed only
  identity, terminal, frequency, `S**2`/stability-text and coordination-
  distance observations, rejected hash/charge/atom-order drift, and kept TS
  acceptance, promotion and submission refused;
- the M2c input observer bound the exact candidate, still-blocked template, M1
  sidecar and existing synthetic input hashes; parsed only Link 0, route,
  charge/multiplicity, atom order, Cartesian and trailing-section facts;
  rejected `--Link1--`, `Geom=Check`, authority, charge and atom-order drift;
  and kept input acceptance, protocol selection, promotion and submission
  refused;
- the M2d sidecar independently recorded wavefunction, coordination, mode and
  input decisions; complete, blocked and reviewer-rejected fixtures preserved
  top-level acceptance, promotion, submission and execution refusal;
- the M1 sidecar builder bound the exact design, still-blocked template,
  unsupported candidate and review source. Complete and incomplete synthetic
  fixtures preserved the no-default, no-scientific-acceptance, no-promotion and
  no-execution boundary, and the complete synthetic case explicitly did not
  satisfy the real M1 milestone; and
- the BF3 literature builder reproduced the checked ledger byte-for-byte and
  rejected a tampered coordinate fixture by canonical coordinate-block hash;
- BF3-TS1/B1/B2 atom counts, formulas, exact XYZ hashes, geometry fingerprints,
  and declared reaction-coordinate distances were reproduced offline;
- the original BF3-TS1 closed-shell main-group proposal remained historical
  and non-authorizing, while the exact successful `r01` run was recorded in a
  separate sanitized evidence artifact as a mode-consistent first-order
  saddle candidate;
- the sanitized BF3-TS1 evidence contract rejected missing approval provenance,
  payload tampering, and unreviewed vibrational-mode decisions;
- command-line end-to-end tests reproduced the checked BF3 literature ledger,
  generated only a non-runnable smoke proposal, retained the metal submission
  refusal, validated standalone artifacts and the full synthetic hash chain,
  and refused output overwrite;
- the real CAT2 forward study preserved the literature reaction identity and
  both stereochemical comparison channels without fabricating catalyst
  structures, atom maps, candidate geometries, or an ee ensemble;
- the real CAT2 strict ChemDraw-to-W1 smoke passed native ChemDraw round-trip,
  zero-warning strict document validation, three-fragment molecular
  re-extraction, sole-product `S` CIP review, balanced occurrence accounting
  and all three hash-bound W1 validators while retaining two species and six
  condition-model blockers;
- the approved live OpenAlex smoke resolved the target JACS DOI
  `10.1021/jacs.4c09067`, ranked it above an unrelated photocatalytic hit, and
  finalized a hash-bound evidence review while preserving the CAT2-versus-
  achiral-BF3/BCF model boundary and all missing-upstream promotion blockers;
- Crossref was intentionally skipped because no contact email was configured,
  publisher full text remained inaccessible, and those coverage limits were
  retained explicitly rather than silently upgraded to primary-article proof;
- the full repository suite completed 127 tests successfully, including the
  repository-wide Auto-G16 naming gate, reaction-literature fixture replay,
  evidence-review refusals and the non-authorizing reusable-knowledge-database
  and literature boundaries;
- the `skill-creator` structural validator reported `Skill is valid!`;
- the literature ledger and smoke-proposal payload hashes were independently
  reproduced; and
- `git diff --check` plus the targeted password/API-key/private-key scan found
  no problem in the scoped change files.

No live SSH, PBS, Gaussian, cancellation, or server-data command was part of
this validation. The approved external actions were limited to metadata search
and synchronization of the one named local Skill; neither grants Gaussian or
PBS authority.

This snapshot contains offline development evidence plus the approved metadata-
search smoke. It is not Gaussian or chemical validation.

## Protocol-rigor gate implemented offline

The input-preparation workflow now has a prospective three-candidate protocol
gate for every new calculation need:

1. create `gaussian-protocol-options/1` with `loose`, `standard` and `strict`
   protocol candidates before writing a Gaussian input;
2. mark scientifically unresolved or unsupported candidates `blocked` instead
   of inferring a functional, basis/ECP, solvent, spin treatment, TS/IRC method
   or thermochemistry policy;
3. record the user's explicit selection as a separate immutable, hash-bound
   `gaussian-protocol-selection/1` decision; and
4. allow only the exact offline input draft from that decision, while retaining
   the separate rendered-input hash and live submission approval gate.

The standard-library `protocol_selection.py` CLI implements
`propose`/`select --confirmed`/`validate`, refuses overwrite, and creates no
Gaussian input, SSH, PBS or live action. Its options artifacts intentionally
contain no route, input, project, server or job fields.

Offline tests cover exact three-tier membership, Chinese display labels,
scientifically distinct candidates, request/proposal/option/selection/approval
hashes, complete per-element basis/ECP coverage, unresolved and unsupported
blocking, selection of blocked candidates, authorization boundaries, resource-
rigor independence, overwrite refusal and CLI round trips. Two independent
forward tests also refused both premature standard-input generation and an
automatically selected strict Pd-TS protocol.

`strict` denotes stronger convergence, evidence or method-sensitivity work and
is not an accuracy guarantee. Protocol rigor is independent of the
`simple`/`general`/`complex` resource tiers.

This gate is prospective. The original BF3-TS1 attempt must not receive a
backdated proposal or selection. The successful Hessian-informed `r01`
recovery, however, was prospectively bound to the reviewed three-tier options,
the user's explicit `standard + complex` selection, the rendered input, and
the exact live approval. Its sanitized evidence can therefore be `passed`
without manufacturing provenance. Any retry, IRC, endpoint or later BF3
candidate still requires its own new gate.

## Next approval gates

1. Continue the W2 `auto-g16-knowledge-base` from the completed W2B-2 offline
   store/import/export foundation with authentication, durable audit logging,
   chemical search and a separately reviewed service boundary. Then implement
   the literature query/evidence/mechanism-support/TS-precedent contracts. Only
   after offline acceptance, separately approve one real-reaction literature-
   search smoke; it must not generate an input or authorize calculation.
2. Use the implemented candidate-bound M1 sidecar for one concrete metal–
   chiral-ligand reaction and review its oxidation/electron accounting, spin
   surfaces, wavefunction, coordination state, method evidence, elementary-
   step class and TS design. Unreported literature fields remain blockers;
   scientific acceptance and runtime support remain refused.
3. Apply the implemented M2d sidecar to one real, field-complete bounded review
   while building M3 adversarial runtime/promotion boundary fixtures without
   rendering a metal Gaussian input or enabling submission.
4. After each BF3-TS2-B1 IRC direction terminates, fetch it, run the exact
   offline terminal-intake template, and independently review its endpoint;
   do not label endpoints or claim path validation before both terminate and
   their endpoint structures are identified.
5. Monitor the approved BF3-TS2-B2 standard job to stable termination, fetch the
   complete Opt/Freq output, run the exact offline intake template, and apply
   the precommitted 228-mode/one-imaginary-mode/C13–C21 animation gates before
   any TS claim.
6. Keep any B1/B2 retry, B2 IRC and full BCF benchmarks separately gated.
7. Resume broader chiral-boron complex construction and enumeration after the
   transition-metal design milestone.

The exact merge/deployment preparation and B1 acceptance checklist are in
`docs/asymmetric-catalysis-v1-readiness.md`. That document does not authorize
either action.

## Working-tree note

At the start of this update, `windows-current-screen.png` was an unrelated
untracked local screenshot. It is intentionally not part of this change.
