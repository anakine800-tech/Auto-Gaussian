---
name: auto-g16-reaction-workflow
description: Build and audit an offline, hash-bound whole-reaction study from reviewed ChemDraw intake through species/condition records, mechanism evidence, TS plans, explicit candidates, a finite DAG, normalized energies, bounded analysis, and reporting; also reproduce the narrow formal calculation-artifact handoffs from exact reviewed sources. Use when Codex must connect these immutable stages or explain a blocker. This Skill never infers chemistry or methods; exact input bytes require the adapter's accepted review and never authorize live work.
---

# Auto-G16 Reaction Workflow

## Purpose

Start a whole-reaction study with three immutable W1 artifacts:

1. `gaussian-reaction-intake/1`;
2. `gaussian-reaction-species-registry/1`; and
3. `gaussian-reaction-condition-model/1`.

Treat these as offline scientific review records. Keep every artifact
`calculation_ready: false` and `no_submission_authorization: true`. A reviewed
intake is not a mechanism, protocol, Gaussian input, batch approval, or live
calculation request. Optional downstream stages remain separate, reviewed,
hash-bound artifacts; no downstream artifact changes that authority boundary.

## Required upstream package

Use `auto-g16-chemdraw-structures` in Strict mode for a reaction drawing containing
reactants, products, arrows, conditions, quantities, catalysts, ligands,
additives, workup, or selectivity. Require its source-exact and normalized
reaction transcription. Do not use a Quick draft as reviewed intake.

The current adapter consumes `normalized_scheme.json` from
`create_reaction_scheme_package.py`. Preserve the original ChemDraw/CDXML/CDX
or source image as a separately hashed source file.

Read [references/intake-contract.md](references/intake-contract.md) before
creating review inputs.

## Workflow

### 1. Scope and build the intake

Prepare `gaussian-reaction-intake-request/1` with the source files, target
question, claim ceiling, explicit non-goals, unresolved transcription and a
review decision. Then run:

```bash
TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/reaction_workflow.py"

python3 "$TOOL" build-intake intake-request.json \
  --scheme normalized_scheme.json --output reaction-intake.json
```

The builder assigns stable step, occurrence and condition IDs, preserves
source-exact values, hashes every source, records blockers and refuses output
overwrite. It does not resolve a label into a molecular identity.

### 2. Build the species registry

Create a separate `gaussian-reaction-species-review/1` bound to the exact
intake payload hash. Give every chemical identity a stable `species_id` and
record its represented form, source occurrences, structure hash, formula,
charge, multiplicity, component count, stereochemistry, protonation,
salt/solvate status and stable atom IDs.

Bind every drawn reactant and product occurrence exactly once. Represent
unshown balance species explicitly; never repair an imbalance by changing a
drawn structure.

```bash
python3 "$TOOL" build-registry reaction-intake.json \
  --review species-review.json --output species-registry.json
```

The builder rejects missing or duplicate occurrence bindings, changed intake
hashes, unknown source/species IDs, symlinked structures and unreviewed required
species. It records unresolved identity, charge, multiplicity, stereochemistry,
protonation, salt/solvate, atom identity or balance as blockers.

### 3. Build the condition model

Create `gaussian-reaction-condition-review/1` bound to both preceding payload
hashes. Give every transcribed condition item exactly one reviewed treatment:

- `explicit_component`;
- `continuum_environment`;
- `chemical_potential`;
- `computational_parameter`;
- `experimental_context_only`;
- `excluded_spectator`;
- `workup_only`; or
- `unresolved`.

Also review standard state, temperature, concentration, pressure and explicit-
component policies. A solvent name does not select a continuum model; a
catalyst or additive does not become a spectator automatically.

```bash
python3 "$TOOL" build-condition-model reaction-intake.json \
  species-registry.json --review condition-review.json \
  --output condition-model.json
```

The builder refuses missing/duplicate decisions, unknown species references,
changed upstream hashes and non-finite values. Unresolved decisions remain
visible blockers.

### 4. Validate and stop at the W1 boundary

```bash
python3 "$TOOL" validate reaction-intake.json
python3 "$TOOL" validate species-registry.json
python3 "$TOOL" validate condition-model.json
```

Report each gate as `reviewed`, `reviewed_with_blockers`, or `blocked`, together
with the blocker list and the next safe offline action.

Stop the W1 stage after the condition model. Any continuation below is a new
offline stage with its own reviewed inputs. W1 itself does not create active-
catalyst hypotheses, mechanism networks, atom correspondence between states,
reference basins, candidate structures, protocols, Gaussian inputs, server
projects, jobs, retries, cancellations, or reports of mechanism/selectivity.

### Optional W3 mechanism-network slice

Invoke this only as a separate offline stage after an immutable W1 chain and
an explicit human-authored network review exist. Read
[references/mechanism-network-contract.md](references/mechanism-network-contract.md),
then run:

```bash
NETWORK_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/mechanism_network.py"

python3 "$NETWORK_TOOL" build reaction-intake.json species-registry.json \
  condition-model.json --review mechanism-network-review.json \
  --output mechanism-network.json
python3 "$NETWORK_TOOL" validate mechanism-network.json
```

This upstream W3 slice validates complete reviewed states, exact atom maps,
connectivity changes, element/charge conservation, competing networks,
reference basins and catalyst-cycle semantics. A noncatalytic network requires
an explicit `not_applicable` decision and null closure diagnostics; it is never
reported as a successfully closed catalyst cycle. The network necessarily
precedes its child mechanism-support artifact,
so it retains a null child binding and `mechanism_support_unavailable`; this is
an ordering blocker, not a claim that the child builder is unimplemented.
Network output remains `calculation_ready: false` and grants no mechanism
promotion, calculation DAG, protocol, Gaussian input, or live authority.

### Optional reviewed calculation-artifact adapter

Use this only after the exact upstream candidate, protocol, input review, or
specialist result artifacts already exist. Read
[references/calculation-artifact-adapter-contract.md](references/calculation-artifact-adapter-contract.md)
before use.

This adapter is currently unreleased repository source and has not been
deployed. Run these commands from the repository root during development.
Named deployment must use the repository's reviewed
`scripts/sync_named_skill.py` plan/apply flow: this Skill's closed
`deployment-package.json` maps the authoritative reaction-workflow contracts,
while the asymmetric-catalysis owner's manifest maps its exact validator and
schemas. Direct directory copying is not a complete deployment package.

```bash
ADAPTER="skills/auto-g16-reaction-workflow/scripts/calculation_artifacts.py"

python3 "$ADAPTER" export-targets candidate-ledger.json \
  --study asymmetric-study.json --import-id reviewed_target_import \
  --output candidate-target-import.json

python3 "$ADAPTER" build-input-handoff promoted-candidate.json \
  --study asymmetric-study.json --options protocol-options.json \
  --selection protocol-selection.json --review exact-input-review.json \
  --output-input reviewed-ts.gjf \
  --output-manifest reviewed-ts.handoff.json

python3 "$ADAPTER" project-energy promoted-candidate.json parsed-ts-result.json \
  --review energy-review.json --output-record reviewed-energy.json \
  --output-lineage energy-lineage.json

python3 "$ADAPTER" link-attempt \
  --external-target-key asymmetric_candidate:study_id:candidate_id \
  --input-handoff reviewed-ts.handoff.json \
  --sanitized-job sanitized-job-observation.json \
  --terminal-intake terminal-intake.json --parsed-result parsed-ts-result.json \
  --mode-review ts-mode-review.json --scientific-decision ts-mode-decision.json \
  --attempt-link-id reviewed_attempt_link --output calculation-attempt-link.json

python3 "$ADAPTER" validate candidate-target-import.json
python3 "$ADAPTER" validate reviewed-ts.handoff.json
python3 "$ADAPTER" validate energy-lineage.json
python3 "$ADAPTER" validate calculation-attempt-link.json
```

Validate an energy projection through its lineage sidecar. The bare reviewed
energy record intentionally has no standalone source pointers and is refused
by `validate`.

Version 1 accepts only one explicit-Cartesian, restricted closed-shell,
main-group, single-guess TS/Freq family. It delegates final input syntax to
`auto-g16-rtwin-pbs`, delegates single-guess family checks to
`auto-g16-ts-irc`, and also delegates parsed-result/terminal classification
and mode-review geometry consistency to that specialist's
`classify_ts_freq_result_facts`, `classify_ts_freq_terminal_facts`, and
`validate_mode_review_geometry` helpers. Attempt linkage also requires parsed
contiguous indices and ordered elements to match the handoff's reviewed atom
order; parsed results do not carry source atom IDs. It consumes rather than
reparses specialist TS result and scientific-review JSON. Metal, open-shell,
QST, IRC, AllCheck/Check,
`Guess=Read`, Link1, general-basis/ECP and non-empty trailing-section variants
remain refused.

The output `.gjf` is only a reproducible offline handoff. Every companion,
target, energy, and observation artifact keeps `calculation_ready: false` and
`no_submission_authorization: true`. The adapter has no stage, submit, retry,
cancel, cleanup, DAG mutation, or resume command.

### 5. Preserve the W2 knowledge and literature gates

The second scientific-modeling round must first query a reviewed reusable
knowledge layer and bind an immutable per-study snapshot. Read
[references/knowledge-database-design.md](references/knowledge-database-design.md)
when binding the implemented offline structure, method, and literature/book
registries.

Then obtain reproducible literature evidence before reviewing mechanism
support or TS seed strategies. Read
[references/literature-evidence-design.md](references/literature-evidence-design.md)
when preparing that handoff.

The separate `auto-g16-knowledge-base` Skill implements the offline immutable
registry, permission-filtered index, typed-link and snapshot MVP. This W1
builder does not invoke it automatically or fabricate a snapshot. The separate
`auto-g16-reaction-literature` Skill implements the query, metadata retrieval,
screening and source-evidence stages. This Skill now also owns separate offline
mechanism-support and TS-precedent-map builders described below. This W1
builder still performs none of those
actions. Do not claim that a database was queried or updated, claim that a
search was performed without its immutable artifacts, infer a mechanism from a
citation, or transfer an unreviewed structure/geometry. A database match and
literature similarity do not prove the target mechanism or TS and grant no
calculation authorization.

### Optional reviewed mechanism-support gate

Invoke this only after the immutable W1/network chain, knowledge snapshot,
finalized literature evidence and a human-authored edge/channel review exist.
Read
[references/mechanism-support-contract.md](references/mechanism-support-contract.md),
then run:

```bash
SUPPORT_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/mechanism_support.py"

python3 "$SUPPORT_TOOL" build mechanism-network.json knowledge-snapshot.json \
  literature-evidence.json --review mechanism-support-review.json \
  --output mechanism-support.json
python3 "$SUPPORT_TOOL" validate mechanism-support.json
```

The artifact keeps evidence classification separate from two independent
decisions. A reviewed novel edge may be `hypothesis_exploration_eligible` when
no direct precedent was found, but it remains not literature-supported and not
mechanism-validated. Direct evidence, analogy, internal rationale,
contradictions and missing precedent remain distinct. Every output remains
offline and non-authorizing.

### Optional reviewed TS-precedent and de novo seed map

Invoke this only after an immutable W1 chain, reviewed mechanism-network
artifact, reviewed knowledge snapshot, finalized literature evidence with all
four W1/knowledge bindings, and an explicit human-authored precedent review
exist. Read
[references/ts-precedent-map-contract.md](references/ts-precedent-map-contract.md),
then run:

```bash
PRECEDENT_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/ts_precedent_map.py"

python3 "$PRECEDENT_TOOL" build mechanism-network.json knowledge-snapshot.json \
  literature-evidence.json mechanism-support.json \
  --review ts-precedent-review.json \
  --output ts-precedent-map.json
python3 "$PRECEDENT_TOOL" validate ts-precedent-map.json
```

This converts reviewed edges and evidence into immutable atom-correspondence,
geometry-transfer-scope and seed-strategy review records. It copies no
coordinates and constructs no geometry. The exact mechanism-support edge and
channel must be exploration-eligible. A novel edge with no direct precedent
may use a separate de novo endpoint/QST, scan or reviewed-rebuild plan with
`source_precedent: null` and `source_coordinates_used: false`; that does not
make the mechanism claim literature-supported or validated.

### Materialize reviewed candidates and derive the calculation plan

Read
[references/orchestration-and-analysis-contract.md](references/orchestration-and-analysis-contract.md).
The first TS-candidate implementation materializes only an explicitly accepted
`published_coordinates` main-group precedent whose gate is
`candidate_construction_eligible`. It independently rechecks the exact
mechanism-support gate, source atom order/mapping, charge, multiplicity, source
object, and generated XYZ. State candidates require explicit reviewed single-
structure or multi-component complex coordinates. The tool does not pack
fragments, generate conformers, or materialize de novo plans, and it refuses
transition-metal inventories.

```bash
ORCHESTRATOR="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/reaction_orchestrator.py"

python3 "$ORCHESTRATOR" build-candidate ts-precedent-map.json \
  --review candidate-review.json --xyz-output ts-seed.xyz \
  --output ts-candidate.json
python3 "$ORCHESTRATOR" validate-candidate ts-candidate.json

python3 "$ORCHESTRATOR" build-state-candidate mechanism-network.json \
  --review state-candidate-review.json --xyz-output state-seed.xyz \
  --output state-candidate.json
python3 "$ORCHESTRATOR" validate-candidate state-candidate.json

python3 "$ORCHESTRATOR" build-dag mechanism-network.json ts-precedent-map.json \
  --review calculation-dag-review.json --output calculation-dag.json
python3 "$ORCHESTRATOR" validate-dag calculation-dag.json

python3 "$ORCHESTRATOR" build-index mechanism-network.json \
  mechanism-support.json ts-precedent-map.json calculation-dag.json \
  --candidate ts-candidate.json --candidate state-candidate.json \
  --output study-index.json
python3 "$ORCHESTRATOR" validate-index study-index.json
```

The DAG is a finite dependency/evidence plan, not a scheduler. The study index
is derived from exact artifacts and keeps eligible, unimplemented de novo seed
construction visible as a next offline review action. Never edit its status or
next actions by hand. Candidate and DAG readiness cannot bypass the separate
protocol, rendered-input, and exact live-submission gates owned by other
Skills.

### Normalize energy evidence and render a bounded report

Use reviewed JSON pointers and thermochemical definitions to normalize each
state or TS result, then derive only comparisons sharing one temperature,
standard state, and energy model:

```bash
ANALYSIS="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/reaction_analysis.py"

python3 "$ANALYSIS" build-energy mechanism-network.json calculation-dag.json \
  --review reaction-energy-record-review.json --output energy-record.json
python3 "$ANALYSIS" validate-energy energy-record.json

python3 "$ANALYSIS" build-analysis mechanism-network.json calculation-dag.json \
  --energy energy-record.json --review analysis-review.json \
  --output reaction-analysis.json
python3 "$ANALYSIS" validate-analysis reaction-analysis.json

python3 "$ANALYSIS" build-report study-index.json reaction-analysis.json \
  --review report-review.json --markdown-output reaction-report.md \
  --output reaction-report.json
python3 "$ANALYSIS" validate-report reaction-report.json
```

Repeat `--energy` for every reviewed record. Real-result claim eligibility
requires terminal DAG evidence and the applicable stationary-point and TS-mode
gates. Synthetic fixtures always retain `contract_fixture_only`. Eyring
comparisons require explicit activities; uncertainty scenarios are reviewed
energy offsets, not an inferred method-error estimate. The report validator
re-renders the Markdown and rejects content or hash drift.

Do not pass the formal adapter's `gaussian-energy-lineage/1` or bare
`gaussian-reviewed-energy-record/1` into this comparison layer: that V1
projection is deliberately electronic-only and always
`comparison_eligible: false`. It may be retained as independently validated
DAG evidence, but common-reference analysis requires a separate complete
thermochemical record with its exact candidate, protocol, terminal, and mode
lineage. The similarly named review schemas are distinct; do not substitute
`gaussian-energy-review/1` for
`gaussian-reaction-energy-record-review/1`.

## Scientific boundaries

- Preserve source-exact values beside normalized values. Never turn `rt`,
  `overnight`, `trace`, unreadable quantities or an omitted species into an
  invented number or identity.
- Distinguish one chemical identity from its conformers and coordination,
  association, ion-pair, protonation, oxidation and solvation states.
- Do not infer an active catalyst from a precatalyst drawing.
- Do not call a synthetic equation element/charge balanced when workup,
  counterions, bases, gases or byproducts remain unrepresented.
- Do not infer a functional, basis/ECP, solvent model, temperature correction,
  standard state, mechanism, TS algorithm or resource tier.
- Keep transition-metal, open-shell, broken-symmetry, multireference and
  ambiguous coordination cases blocked for later specialist review.

## Bundled resources

- `scripts/reaction_workflow.py`: standard-library-only deterministic W1
  builders and validator.
- `references/intake-contract.md`: required review-input fields, semantics and
  blocker rules.
- `references/knowledge-database-design.md`: W2 structure, method, and
  literature/book registry, immutable snapshot, permission and storage/index
  contract implemented offline by `auto-g16-knowledge-base`; multi-user service
  and raw legacy migrations remain future work.
- `references/literature-evidence-design.md`: W2 reproducible search, evidence
  extraction, applicability review, mechanism-support and TS-precedent design.
  The query and evidence stages are implemented by
  `auto-g16-reaction-literature`; the strict offline mechanism-support and
  TS-precedent/de novo-planning slices are implemented here.
- `references/mechanism-support-contract.md`: implemented immutable-parent,
  edge/channel evidence classification, independent exploration and claim-
  support decisions, contradiction handling and fail-closed rules.
- `references/ts-precedent-map-contract.md`: implemented immutable-parent,
  atom-correspondence, geometry-transfer, strategy and fail-closed promotion
  rules for `gaussian-ts-precedent-map/1`.
- `references/mechanism-network-contract.md`: implemented first W3 offline
  review/output semantics, fail-closed diagnostics and mandatory evidence
  blocker.
- `scripts/mechanism_network.py`: standard-library-only deterministic W3
  mechanism-network builder and validator; no calculation or live path.
- `scripts/mechanism_support.py`: standard-library-only deterministic evidence
  classification and two-gate builder/validator; no calculation or live path.
- `scripts/ts_precedent_map.py`: standard-library-only deterministic TS
  precedent-map builder and validator; no coordinate or input construction.
- `scripts/calculation_artifacts.py`: standard-library-only target-import,
  exact input-handoff, blocked/electronic-only energy-lineage and immutable
  attempt-link adapters; no live path.
- `references/calculation-artifact-adapter-contract.md`: exact source,
  authority, refusal, energy-lineage and future DAG-owned importer contract.
- `scripts/reaction_orchestrator.py`: reviewed candidate materialization,
  finite calculation DAG, and derived study-index tooling. Formal adapter
  evidence is owner-validated but cannot change DAG completion before a
  separately reviewed external-target-to-node mapping exists.
- `scripts/reaction_analysis.py`: energy normalization, bounded analysis, and
  deterministic report tooling.
- `references/orchestration-and-analysis-contract.md`: candidate, DAG, index,
  thermochemistry, kinetics, uncertainty, and report semantics.
- `contracts/reaction-workflow/` in the repository: Draft 2020-12 output
  schemas for the W1/network/support/TS-planning chain, formal calculation-
  artifact adapter family, and bounded orchestration/analysis artifacts.
