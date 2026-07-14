# Protocol rigor proposal and selection

Use this gate after a calculation need has been stated and before any Gaussian
input is written. It separates scientific protocol choice from input rendering
and from live submission approval.

## Required sequence

1. Review the chemical identity, structure, stereochemistry, charge,
   multiplicity, job type, intended claim, environment and unsupported-method
   concerns.
2. Create one immutable `gaussian-protocol-options/1` proposal containing
   exactly three named candidates: `loose`, `standard` and `strict`.
3. Show the complete candidates and their limitations. Do not select one on
   the user's behalf.
4. Record the user's explicit selection as a separate immutable
   `gaussian-protocol-selection/1` artifact bound to the proposal and
   calculation-request hashes.
5. Only then may an offline builder render an input draft using exactly the
   selected settings. Preserve the proposal and selection hashes in the input
   manifest.
6. Show the rendered input and its SHA-256 and obtain the existing exact live
   approval before staging or submission.

A protocol selection authorizes only the offline input draft in step 5. It
does not authorize SSH, server-directory creation, transfer, `qsub`, an IRC,
a retry, cancellation, cleanup, or any later calculation.

Use the standard-library-only CLI for this state transition:

```bash
TOOL="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/protocol_selection.py"

python3 "$TOOL" propose request.json --profiles reviewed_profiles.json \
  --output protocol_options.json
python3 "$TOOL" select protocol_options.json --tier standard \
  --approval-record user_decision.json --confirmed \
  --output protocol_selection.json
python3 "$TOOL" validate protocol_selection.json \
  --options protocol_options.json
```

`propose` and `validate` are offline operations. `select --confirmed` records
the user's already-made decision; the flag is not permission to submit.

## Artifact bindings

Every item in `gaussian-protocol-options/1.options` has an `option_id`, one of
the three `tier` values, `rigor_rank` 1/2/3, `option_status`, purpose,
applicability, method profiles, task/validation/coverage plans, resources,
expected cost, limitations, provenance and its own payload SHA-256. The
resource record includes the independent resource tier, memory, cores, job
count, relative cost and assumptions. Cost is qualitative/relative; do not
promise wall time.

Keep proposal artifacts route-free and input-free. They describe the reviewed
stage-specific scientific settings needed to compose a route, but contain no
Gaussian route, Link 0 field, input text, checkpoint, project, server path or
job identifier. The confirmed selection authorizes only the subsequent offline
route/input draft.

`gaussian-protocol-selection/1` binds `options_source`, `request_sha256`, the
exact `selected_option`, calculation `scope_binding`, external
`approval_evidence`, the fact that alternatives were reviewed, explicit
`authorizations` and its payload SHA-256. Its authorizations must permit only
the selected offline input draft and deny live actions.

## Meaning of the three candidates

The names describe intended evidence and effort, not universal methods:

- `loose`: screening or diagnostic work with an explicitly limited claim
  scope. It may use a less expensive method or basis and looser numerical
  settings only when those choices are scientifically applicable. It is not a
  final selectivity or thermochemistry protocol by default.
- `standard`: the primary reviewed production candidate for the stated
  question. It should include the optimization/frequency, solvation,
  thermochemistry and single-point stages needed for that question.
- `strict`: a stronger convergence, basis, model or method-sensitivity plan for
  the stated question. It may be a protocol stack rather than one larger-basis
  route. The label is not an accuracy guarantee and does not prove that the
  underlying model, mechanism, functional or basis is correct.

Do not populate the candidates by scaling one remembered route. For every
candidate record, stage by stage when applicable:

- functional or electronic-structure method;
- basis coverage for every element and any ECP or relativistic treatment;
- dispersion, solvent model and explicit-solvent assumptions;
- optimization, frequency, TS, IRC and endpoint settings;
- integration grid, SCF and convergence settings;
- temperature, standard state and low-frequency policy;
- single-point and composite-energy definition;
- intended claim scope, limitations and comparison rules; and
- proposed memory, cores, expected stages and relative cost.

Literature settings are evidence for a candidate, never an automatic default.
All members of a comparison group still need a common reviewed protocol or an
explicit balanced comparison design.

## Scientific refusal and blocked candidates

Do not infer a method, basis/ECP, solvent, spin treatment, TS algorithm, IRC
settings or low-frequency correction from molecular appearance or from the
requested rigor label. Mark a candidate `blocked` instead of rendering a route
when any required scientific choice is unresolved or when the current Skills
do not support the case.

Blocking conditions include, as applicable:

- unresolved identity, structure, stereochemistry, atom map, charge or
  multiplicity;
- missing element coverage, ECP or relativistic treatment;
- unresolved solvent, temperature, standard state or reference-energy model;
- transition-metal, open-shell, broken-symmetry, excited-state,
  multireference, periodic or ONIOM requirements outside current support;
- an unreviewed TS coordinate, QST syntax, IRC direction/integrator or endpoint
  model; and
- a proposed method whose applicability cannot be justified for the requested
  claim.

The proposal must still display all three names. One or more candidates may be
blocked, and if every candidate is blocked no selection may authorize an input
draft. Never weaken a blocked condition merely to fill all three rows.

## Rigor and resources are orthogonal

`loose`, `standard` and `strict` are protocol-rigor candidates.
`simple`, `general` and `complex` are server resource tiers. They are separate
decisions:

- a strict protocol can fit the `simple` resource tier for a small system;
- a loose screening calculation can need `complex` resources for a large
  system; and
- more cores or memory do not make an unsuitable method scientifically valid.

Show the exact `%mem`, `%nprocshared` and PBS request independently of the
selected rigor candidate. Resource approval never substitutes for protocol
selection.

## Immutability and later changes

Bind the selection to the exact options artifact, request, structure and
selected-option payload. Refuse an altered proposal, selection, structure, route,
basis, solvent, resource request or stage definition. A changed setting creates
a new proposal and a new selection; it is not an edit or an automatic retry.

The final rendered input remains subject to a separate hash-bound review. A
successful calculation does not promote another rigor candidate or authorize a
subsequent stage.

## Existing BF3-TS1 run

The BF3-TS1 calculation that was already approved and started before this gate
was introduced is historical live evidence. Do not manufacture or backdate a
protocol proposal or selection for it. Preserve its actual approval and input
provenance as-is. Apply this gate prospectively to any new BF3-TS1 retry,
BF3-TS2 candidate, IRC, endpoint or other calculation.
