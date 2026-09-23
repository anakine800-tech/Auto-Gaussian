# Auto-G16 v3 boundary: v31-shared

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:4860-5148 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V31-SHARED-CONTRACT-01 shared execution and ensemble contract

This section freezes contract only. It defines no product classes, schema
files, registry implementation, parser, transport operation, command renderer,
or live effect.

### Exact change disposition

| Disposition | Frozen V31 treatment |
| --- | --- |
| **KEEP** | Core `Project` remains exactly `{project_id}`; the Core schema, Task/Attempt lifecycle, approvals, no-overwrite, at-most-one effect, `REPLAY` zero effect, `UNKNOWN` reconciliation-only, and no automatic retry stay authoritative. The V30 Gaussian generation remains production-usable for DFT SP/Opt/Freq/Opt+Freq. |
| **ADD** | One Project first-use physical-provisioning contract and provisioning-domain `ProjectPhysicalBinding`; the private closed ProgramAdapter registry; public `SamplingProfile`, `ConformerEnsemble`, and `ThermodynamicEnsemble` ensemble records. |
| **VERSIONED SUCCESSOR** | Public execution records `ProgramExecutionSpec` and `ProgramExecutionSnapshot` are mandatory for xTB/CREST Attempts. A future Gaussian Attempt may use them only after separate adapter implementation/validation; V31 acceptance requires no Gaussian migration. |
| **DO NOT TOUCH** | V30 `PreparedInputBinding`, `PbsTemplateBinding`, `ExecutionSnapshot`, and vectors; Core Project shape/schema; Approval, Workflow, Observe, Result, ScientificValidation, and Review public contracts; Transport topology/protocol/operations; every current parser and grammar; live/deployment behavior. |

The future V31 product must expose no more than the two named new execution-
domain records. `ProjectPhysicalBinding` is owned by the separate provisioning/
physical-authority boundary and is not an execution record. Nested closed
values described below are record fields, not additional public execution
records, protocols, adapters, or extension bags.

### Project first-use physical provisioning

`ProjectPhysicalBinding` has these mandatory semantic fields:

- `project_physical_binding_id` and `project_id`;
- `provisioning_contract_version`;
- an ordered, non-empty `locations` tuple whose closed members bind
  `location_kind`, reviewed root, exact Project directory, provisioning
  disposition, retained parent physical identity, resulting Project-directory
  physical identity, and exact create/re-attestation evidence identity;
- the complete identity payload used to derive the record ID.

Location kinds are a closed V31 set selected by the owning target contract;
they do not add a Transport topology or select a program. Resolution has
exactly three branches:

1. **target absent:** under a reviewed no-follow root, one unique intent wins;
   the implementation replays the retained parent identity immediately before
   one exact nonrecursive no-follow mkdir, then durably records the resulting
   Project-directory physical identity in `ProjectPhysicalBinding`;
2. **already Product-bound existing:** the exact durable Product binding is
   loaded first, the current named target is no-follow re-attested to the same
   physical identity, and reuse is idempotent with no second mkdir; or
3. **unbound existing:** an existing target without the exact durable Product
   binding returns `UNBOUND_EXISTING`, performs zero effects, and stops for a
   later explicit Owner migration/adoption decision.

A non-directory, symlink/reparse point, root escape, parent or target
replacement, identity drift, conflicting binding, or implicit adoption fails
closed. A concurrent loser performs zero effects. Provisioning does not
allocate an Attempt, and it may not overwrite, truncate, recursively replace,
delete, or clean any path. An ambiguous first-use effect yields no usable
`ProjectPhysicalBinding`, enters exact same-intent reconciliation, and creates
no automatic retry or alternate-location authority.

The provisioning journal and effect receipt are private implementation details
for a later contract. They live outside the Core schema. Their future design
must preserve the above outcomes and cannot be inferred from legacy v2 owner,
receipt, or capability machinery.

### Additive versioned multi-program execution successor

Generation selection is per Attempt, not per Workflow or Batch. A V31 Workflow
or Batch may intentionally contain both:

- V30-generation Gaussian Attempts for DFT single-point, optimization,
  frequency, or combined optimization/frequency work, using the unchanged
  `PreparedInputBinding`, `PbsTemplateBinding`, and `ExecutionSnapshot`; and
- successor-generation xTB/CREST Attempts using `ProgramExecutionSpec` and
  `ProgramExecutionSnapshot`.

The exact generation is fixed before effect authority. One Attempt binds
exactly one generation, never both, and no in-place generation conversion is
permitted. Neither Workflow nor Batch imposes one generation on every member.
A future Gaussian successor Attempt is optional and requires its own separately
implemented and validated adapter. V31 acceptance does not require or imply
migration of a Gaussian Task or Attempt.

`ProgramExecutionSpec` has these mandatory semantic fields:

- `program_execution_spec_id`, `program_kind`, `adapter_id`, and positive
  `adapter_contract_version`;
- an ordered, non-empty closed `exact_inputs` tuple binding logical role,
  portable name, format, SHA-256, and size for every immutable input byte set;
- closed `program_data` matching the exact adapter/version schema, with no
  unknown key, extension bag, callback, or executable content;
- closed `invocation` semantics binding exact executable identity, ordered argv
  tokens, declared stdin/data source, and closed environment inputs; and
- ordered `required_outputs` and `optional_outputs` tuples, each with exact
  logical role, portable path/name grammar, format, cardinality, size/capture
  policy, and required completeness meaning.

An output cannot appear in both tuples. Missing required output is failure;
missing optional output is an explicit absent observation and cannot change
overall program success semantics unless the exact adapter version says so.
The spec contains no Attempt, resource, target, workspace, or scheduler choice.

`ProgramExecutionSnapshot` has these mandatory semantic fields:

- `program_execution_snapshot_id`, `attempt_id`, `effect_intent_id`,
  `calculation_plan_id`, and positive `calculation_plan_revision`;
- the exact `program_execution_spec_id` and spec payload hash;
- the exact `project_physical_binding_id` and one exact Attempt workspace below
  a bound Project location;
- the resolved resource and target bindings, exact cwd binding, plus any
  derived scheduler artifact identities required by that target; and
- the complete canonical identity payload used to derive both the effect
  intent and snapshot IDs.

The snapshot is the sole successor-generation program-effect meaning. It is
immutable and self-authenticating; any byte, token, parameter, adapter version, resource,
target, Project binding, workspace, or output-declaration change requires a new
snapshot and current approval/confirmation under a later implementation
contract. A V30-generation Attempt cannot acquire a `ProgramExecutionSpec` or
`ProgramExecutionSnapshot`; a successor-generation Attempt cannot carry V30
`PreparedInputBinding`, `PbsTemplateBinding`, or `ExecutionSnapshot` authority.
The owning Workflow/Batch may still contain other Attempts from the other
generation.

`ProgramExecutionSpec.program_kind` is exactly one of `gaussian`, `xtb`, or
`crest`. `ProgramAdapter` is the name of a private closed registry role only.
The registry contains exactly the three program kinds above and maps each exact
`(program_kind, adapter_id, adapter_contract_version)` key to closed data
validation and deterministic rendering. It exports no public adapter object,
generic plugin hook, arbitrary program name, or caller registry mutation.
Unknown keys fail closed. Initial V31 implementation acceptance requires the
successor only for xTB and CREST. Registry vocabulary for `gaussian` is not an
implemented or production-qualified Gaussian successor and creates no migration
requirement; that route remains behind a later adapter implementation and
validation gate.

Primary invocation semantics live in `ProgramExecutionSpec` as an executable
identity plus argv tokens and typed data. Every token is separately represented
and validated; process creation is non-shell. A `command`, `command_line`, or
equivalent shell string cannot be the primary meaning or a fallback. Ambient
PATH, shell expansion, caller environment, response files, and undeclared files
cannot supply missing semantics. When PBS or another unchanged target mechanism
needs script bytes, the private renderer deterministically derives and byte-
binds that secondary artifact from the closed snapshot. The script cannot
replace the argv/data meaning. This contract adds no AGV3 operation, SSH hop,
PBS dialect, transport route, parser, or result grammar.

The xTB adapter contract version 2 additionally requires the resolved target to
own canonical `platform_paths["xtb_data_path"]` and canonical runtime content
named `xtb-runtime-data-manifest-v1.json` with schema
`auto-g16-v31-xtb-runtime-data-manifest/1`. The manifest is normalized before
its existing runtime byte identity is derived, so JSON formatting and object-key
order are non-semantic while any file path, size, or SHA-256 change invalidates
the resolved profile. Its closed invocation environment contains exactly
`OMP_NUM_THREADS` sourced from `ResolvedResourceRequest.cores` and `XTBPATH`
sourced from the resolved profile path. The scheduler renderer emits that exact
path; callers cannot provide, override, or derive it from PATH, HOME, shell
profiles, or modules. The current CREST adapters remain unchanged.

### Independent SamplingProfile policy record

`SamplingProfile` is an independent public ensemble-domain record with these
mandatory semantics:

- `sampling_profile_id`, immutable revision/supersession binding, exact species
  and electronic-state scope, and exact stereochemical scope;
- closed route/category definitions, engine and implementation identities,
  immutable configuration identities, seeds, constraints, and reviewed
  allocation/quotas;
- candidate-legality rules for atom map/order, connectivity, explicit
  hydrogens, charge, multiplicity/state, fragments, stereochemistry, finite
  geometry, clashes, association/dissociation, and required/forbidden changes;
- the complete cluster/dedup metric, descriptor weights, units, thresholds,
  symmetry treatment, independent-backend requirements, tie-breaks, and
  category-crossing rules;
- explicit coverage criteria and exact failure/blocker semantics; and
- explicit thermodynamic-eligibility and TS-seed-eligibility policies.

The profile is separate from `ConformerEnsemble` because policy must be frozen
before candidate observations, independently identified, and reusable without
copy drift across immutable ensemble revisions. An ensemble embeds the exact
profile identity and payload hash; it cannot override any policy value.

Every applicable numeric or categorical policy value is explicit. V31 defines
no universal `6 kcal/mol` window, Top-N, RMSD threshold, A/B route quota,
temperature, or implicit fallback. Values from legacy conformer Skills are
reuse/benchmark evidence only. `null`, omission, and implementation defaults
cannot silently select policy; a genuinely inapplicable field uses an explicit
closed tagged disposition with rationale.

### ConformerEnsemble minimum public shape

`ConformerEnsemble` has these mandatory semantic fields:

- `conformer_ensemble_id`, `project_id`, exact source CalculationPlan/revision,
  and the exact `sampling_profile_id` plus profile payload hash;
- one closed `species_binding` covering graph and atom-order identities,
  explicit hydrogens, fragments, charge, multiplicity, electronic-state family,
  and atom mapping;
- one closed `stereochemistry_binding` covering every specified center, axis,
  face, geometric isomer, and binding-mode/category identity applicable to the
  reviewed species;
- ordered source provenance and immutable geometry provenance for every member,
  including coordinates identity, atom order, source observation/execution,
  engine/configuration/seed lineage, and any accepted minimum evidence;
- complete sampling observations; a complete audit and negative-evidence
  ledger with every rejection and reason; explicit cluster membership, medoid,
  dedup comparison/decision, independent-backend review, and deterministic
  tie-break evidence; and
- the exact coverage evaluation, ordered `thermodynamic_eligible_members`, and
  ordered `ts_seed_members` projections.

One ensemble contains exactly one species graph, atom order, charge,
multiplicity, and electronic-state family. Cross-state ranking or population is
forbidden. Different reviewed stereochemical or category identities are not
silently merged. Geometry identity never implies minimum or TS acceptance.
Sampling/FF/xTB/CREST energies remain provenance and cannot become formal DFT
thermodynamics or barriers.

Member eligibility is derived, never asserted. The deterministic projections
filter the canonical member order through the exact SamplingProfile policy and
the recorded audit/minimum evidence. Missing evidence, an unresolved audit,
failed coverage, state/stereo drift, incompatible geometry lineage, or required
independent-backend blocker makes the affected projection unavailable rather
than choosing a fallback subset.

`ts_seed_members` is the complete V31 TS-seed handoff from the ensemble. It
does not select a reaction, reaction coordinate, primary/backup portfolio, TS
algorithm, or method and does not claim that a member is a TS. An independent
TS-seed record would duplicate the ensemble member identity and drift from the
same audit lifecycle, so V31 intentionally does not add one. The later
TS-seed workflow consumes an eligible member and separately binds the exact
reaction hypothesis, atom mapping, coordinate lineage, and review gates.

### ThermodynamicEnsemble handoff

`ThermodynamicEnsemble` has these mandatory semantic fields:

- `thermodynamic_ensemble_id`, exact `conformer_ensemble_id` and payload hash,
  and the exact ordered source member set, which must equal the available
  `thermodynamic_eligible_members` projection;
- temperature with units, a complete standard-state definition and conversion
  convention, and the gas constant/unit convention used by aggregation;
- a closed low-frequency treatment binding with scheme name/version, every
  parameter and unit, interpolation/cutoff rules, mode-selection semantics,
  and the exact implementation package/version/source identity;
- one exact method-compatibility binding covering geometry, frequencies,
  electronic energies/corrections, solvent/environment, reference/state,
  basis/model, symmetry-number convention, and result-contract identities;
- for each conformer, exact result provenance, raw RRHO components and raw
  standard-state Gibbs energy, separately recorded treated qRRHO components
  and treated Gibbs energy, degeneracy and its scientific rationale, inclusion
  status, relative statistical weight, and normalized population; and
- the reference member, relative partition function, ensemble treated free
  energy, population normalization evidence, and deterministic identity
  payload.

No temperature, standard state, low-frequency scheme/cutoff/interpolation,
implementation, degeneracy, or method-compatibility value is inferred or
defaulted. Every included conformer must be method-compatible under the one
binding. A missing or incompatible eligible member blocks the ensemble; the
builder cannot silently renormalize a convenient subset. Degeneracy cannot
duplicate a rotational symmetry number or another statistical factor already
included by the raw RRHO implementation.

For treated per-conformer free energies `G_i` at the bound temperature, with
explicit degeneracies `d_i`, the aggregation is:

```text
G_ref = min_i(G_i)
w_i   = d_i * exp(-(G_i - G_ref) / (R*T))
Q_rel = sum_i(w_i)
p_i   = w_i / Q_rel
G_ens = G_ref - R*T*ln(Q_rel)
```

The stored raw RRHO values are evidence and are never overwritten by treated
values. Low-frequency treatment is applied once per conformer before the
ensemble sum. Because `Q_rel` already represents conformer mixing and
degeneracy, a separately calculated conformational entropy may be reported only
as a diagnostic decomposition; it must not be subtracted from `G_ens` or added
to any member again.

### Zero-effect and compatibility boundary

This freeze creates no implementation authority. It does not provision a
Project, allocate or mutate an Attempt, create structures, run a program,
render an input/script, invoke a process, parse output, move data, or accept a
scientific result. Product/API/schema implementation, tests/vectors, and any
live use each require a later exact Owner gate. The Core schema, Transport
topology, current parsers, V30 vectors, and all pre-existing public meanings
remain byte- and semantics-preservation targets for that later work.
