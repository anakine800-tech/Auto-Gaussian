---
name: auto-g16-reaction-workflow
description: Build the offline, hash-bound foundation of a whole Gaussian reaction study from a reviewed ChemDraw reaction package, and create narrow immutable calculation-artifact handoffs only from exact reviewed candidate, protocol, input-draft, and specialist-result artifacts. Use when Codex must scope a reaction-computation study, bind reaction/species/condition records, export candidate-target envelopes, reproduce an explicitly reviewed closed-shell main-group input, or project blocked/electronic-only energy lineage. This Skill never infers mechanisms or methods and never authorizes live work.
---

# Auto-G16 Reaction Workflow

## Purpose

Create the first three immutable artifacts of a whole-reaction study:

1. `gaussian-reaction-intake/1`;
2. `gaussian-reaction-species-registry/1`; and
3. `gaussian-reaction-condition-model/1`.

Treat these as offline scientific review records. Keep every artifact
`calculation_ready: false` and `no_submission_authorization: true`. A reviewed
intake is not a mechanism, protocol, Gaussian input, batch approval, or live
calculation request.

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

Stop after the condition model. W1 does not create active-catalyst hypotheses,
mechanism networks, atom correspondence between states, reference basins,
candidate structures, protocols, Gaussian inputs, server projects, jobs,
retries, cancellations or reports of mechanism/selectivity.

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
reference basins and catalyst-projection closure. It does not infer any of
them. The network necessarily precedes its child mechanism-support artifact,
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

Then obtain reproducible literature evidence before promoting mechanism
networks or TS seed strategies. Read
[references/literature-evidence-design.md](references/literature-evidence-design.md)
when planning that future layer.

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

### Optional mechanism-support matrix view

Use this only after the exact owner-validated
`gaussian-reaction-mechanism-support/1` artifact exists and a separate human-
authored matrix review is complete. Read
[references/mechanism-support-matrix-contract.md](references/mechanism-support-matrix-contract.md),
then run:

```bash
MATRIX_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/mechanism_support_matrix.py"

python3 "$MATRIX_TOOL" build mechanism-support.json \
  --review mechanism-support-matrix-review.json \
  --output mechanism-support-matrix.json
python3 "$MATRIX_TOOL" validate mechanism-support-matrix.json
```

`gaussian-reaction-mechanism-support-matrix/1` is a distinct comparison view,
not a new version or alias of the evidence gate. Its rows and cross-evidence
cells cannot change owner support records or either owner decision. A matrix
row becomes downstream-reviewable only when its reviewed comparison disposition
and the unchanged owner exploration gate both permit another offline review.
It never proves a mechanism, creates a TS seed or executable DAG node, selects
a protocol, authorizes calculation, or mutates an upstream artifact.

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
- `references/mechanism-support-matrix-contract.md`: separate immutable matrix-
  view ownership, exact support/network binding, complete row-by-record
  coverage, evidence-gate compatibility and explicit PR #19 migration rules.
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
- `scripts/mechanism_support_matrix.py`: standard-library-only deterministic
  comparison-view builder/validator over the exact owner support artifact; no
  chemistry inference, DAG mutation, calculation or live path.
- `scripts/ts_precedent_map.py`: standard-library-only deterministic TS
  precedent-map builder and validator; no coordinate or input construction.
- `scripts/calculation_artifacts.py`: standard-library-only target-import,
  exact input-handoff, blocked/electronic-only energy-lineage and immutable
  attempt-link adapters; no live path.
- `references/calculation-artifact-adapter-contract.md`: exact source,
  authority, refusal, energy-lineage and future DAG-owned importer contract.
- `contracts/reaction-workflow/` in the repository: Draft 2020-12 output
  schemas for intake, registry, condition-model, mechanism-network,
  mechanism-support, mechanism-support-matrix review/output, TS-precedent-map
  and the calculation-artifact adapter family.
