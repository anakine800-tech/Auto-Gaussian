# Repository status

Status date: 2026-07-14

Feature branch: `codex/Chiral-Ligand`

Baseline commit: `02ae9bb` (`main` and `origin/main` when this note was written)

## Current capability

The version-controlled source under `skills/` currently provides:

- ChemDraw structure reconstruction and explicit stereochemical review;
- audited ChemDraw/SMILES-to-Cartesian conversion;
- conformer preparation and visible GaussView handoff on RTwin;
- guarded Gaussian 16 transport through RTwin to PBS, including immutable
  hashes, fresh-project enforcement, monitoring, fetch, result parsing, and
  repeated-evidence terminal scheduler-zombie cleanup;
- an offline TS–Freq–IRC scientific layer with single-guess and QST family
  audits, exactly-one-imaginary-mode review, checkpoint-bound AllCheck
  continuations, separately approved IRC directions, and connected or reviewed
  fragmented endpoint evidence; and
- a literature-grounded, offline asymmetric-catalysis planning/audit Skill for
  active-state hypotheses, candidate-space coverage, comparable TS ensembles,
  and bounded selectivity claims.

The TS–Freq–IRC feature and its endpoint workflow have been merged to `main`.
The repository contains tracked live-smoke evidence for the endpoint workflow
and for scheduler-zombie cleanup. Those records are historical evidence only;
they do not authorize another live calculation.

## Work started on this branch

This branch establishes the design, offline data boundary, literature record,
and planning/audit Skill for `gaussian-asymmetric-catalysis`. The intended
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

## Deliberate limitations

- The `gaussian-asymmetric-catalysis` Skill is runnable only as an offline
  planning, deterministic-building, ingestion, and audit workflow. It has no
  Gaussian execution builder or live submission path,
  transition-metal calculation support, or automatic method selection.
- The current `gaussian-ts-irc` Skill explicitly refuses transition-metal,
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
  and is recorded as running pending terminal evidence; operational job files
  remain local and ignored. Full BCF TS1/TS2-B1 remain deferred 87/108-atom
  benchmarks.
- `studies/wang_2024_cat2_alpha_alkylation/`: a real-reaction offline forward
  study that records the reported CAT2 reaction, conditions and selectivity,
  while leaving the unresolved active state, charge/multiplicity, structures,
  atom maps, stereochemical face mapping, candidate coverage and protocol
  explicitly blocked. The linked BF3 ledger remains an achiral mechanistic
  submodel and is not treated as a CAT2 geometry or ee ensemble.
- `contracts/asymmetric-catalysis/*.schema.json`: Draft 2020-12 schemas for the
  study, candidate space, ledger, materializations, candidate, energy record,
  result, analysis, metal-support design, literature benchmark, and smoke
  proposal, plus a sanitized live-smoke evidence record that binds the exact
  approval/input/job/TS/mode chain without retaining a job ID, server path,
  Gaussian log, or checkpoint.
- `tests/fixtures/asymmetric_catalysis/`: non-runnable metal and chiral-boron
  examples.
- `scripts/validate_asymmetric_contract.py`: standard-library-only offline
  structural and cross-artifact semantic validator.
- `skills/gaussian-asymmetric-catalysis/`: offline workflow plus a verified
  Wang-group computational-precedent audit and a candidate/selectivity
  protocol, deterministic builder, and transition-metal support design.
  Publisher PDFs are not stored in the repository.

All design-phase artifacts set or imply `calculation_ready: false` and
`no_submission_authorization: true`. They perform no SSH, PBS, Gaussian,
deployment, cancellation, or server cleanup operation.

## Offline validation snapshot

On 2026-07-14:

- all twelve artifact types passed the repository's fail-closed Draft 2020-12
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
- the metal-support design retained `unsupported_requires_extension` and an
  unconditional submission refusal; and
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
- the full repository suite completed 96 tests successfully;
- the `skill-creator` structural validator reported `Skill is valid!`;
- the literature ledger and smoke-proposal payload hashes were independently
  reproduced; and
- `git diff --check` plus the targeted password/API-key/private-key scan found
  no problem in the scoped change files.

No live SSH, PBS, Gaussian, deployment, cancellation, or server-data command
was part of this validation.

This snapshot is offline development evidence, not Gaussian or chemical
validation.

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

1. Review the literature evidence labels, chemical scope, contract fields, and
   aggregation semantics.
2. Review materialized atom maps, stereochemistry and chemistry-aware complex
   construction needs for a real chiral-boron study.
3. Review the selectivity model, coverage equivalence and sensitivity policy.
4. Review the separate transition-metal scientific design; runtime support
   remains refused.
5. Preserve BF3-TS1 as a mode-consistent first-order saddle candidate; do not
   claim reaction-path validation without separately approved bidirectional
   IRC and identified endpoints.
6. Let the separately approved BF3-TS2-B1 job reach a stable terminal state;
   do not infer progress or failure from an unavailable live connection.
7. Fetch and parse the final B1 log, require stationary-point evidence and
   exactly one raw imaginary frequency, and manually review the C13-C21 mode.
8. Keep any B1 retry, BF3-TS2-B2, all IRC work, and full BCF benchmarks
   separately gated.

## Working-tree note

At the start of this update, `windows-current-screen.png` was an unrelated
untracked local screenshot. It is intentionally not part of this change.
