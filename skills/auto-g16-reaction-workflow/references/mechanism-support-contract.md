# Auto-G16 Mechanism Support Evidence Gate

Status: smallest coherent offline implementation of
`gaussian-reaction-mechanism-support/1`. It classifies evidence against exact
reviewed mechanism edges and stereochemical channels, records a separate
hypothesis-exploration decision, and records a separate mechanism-claim support
decision. It does not infer a mechanism, validate a target mechanism, construct
geometry, choose a protocol, create Gaussian input, or authorize live work.

## Immutable parents

The builder requires exact non-symlinked inputs for:

1. the complete W1 intake, species-registry and condition-model chain bound by
   one valid `gaussian-reaction-mechanism-network/1` artifact;
2. that immutable mechanism-network artifact;
3. a reviewed `auto-g16-knowledge-snapshot/1` whose exact parent is the same
   reaction intake;
4. finalized `gaussian-reaction-literature-evidence/1` with exact bindings to
   the same W1 chain and knowledge snapshot; and
5. an immutable human-authored
   `gaussian-reaction-mechanism-support-review/1` source bound to all six
   upstream payload hashes.

The output records each parent's path, file SHA-256, byte size and payload
SHA-256. Validation resolves and validates every parent, reopens the review
source and independently rebuilds every normalized record and summary. Neither
editing and rehashing an output nor substituting a different review source can
forge the gate.

## Edge/channel records and evidence classification

Every mechanism edge and its exact stereochemical channel must have at least
one support record. Each record repeats and verifies the edge's endpoint state
IDs, complete atom map, forming/breaking pairs and transfers. It also binds one
exact finalized literature candidate and claim, plus the exact source location
when one exists. Deterministic claim and location binding IDs and canonical
payload hashes prevent a similarly worded claim or another location from being
substituted silently.

All nine applicability dimensions are mandatory. Their values must equal the
finalized literature review. Classification and evidence basis remain separate:

- categories are `direct`, `analogy`, `contradictory`, `missing`, or
  `excluded`;
- bases distinguish direct literature support, literature analogy, internal
  rationale, contradictory evidence, absence of direct precedent, later
  experimental evidence, later computational evidence and excluded evidence;
- evidence kind independently records experimental, computational, mixed or
  not-applicable evidence; and
- negative evidence, important mismatches and alternative explanations remain
  visible even when another record is accepted.

Discovery-only, protocol-only and TS-only bounded uses cannot promote a
mechanism claim. Analogy is never silently upgraded to direct support.

## Required scientific review

Every record exactly repeats and reviews:

- both endpoint active-catalyst projections;
- the elementary-step state changes and atom correspondence;
- formal charge, multiplicity and explicit spin descriptions for both states;
- complete coordination contacts and an ion-pair/additive assessment; and
- the exact stereochemical channel and both endpoint stereochemistry records.

The hypothesis review separately records internal rationale, alternatives,
uncertainties, known contradictions and falsifiers. An unresolved atom,
charge, spin, active-state, coordination, ion-pair or stereochemical defect
prevents exploration eligibility.

## Two independent gates

`hypothesis_exploration_eligible` and `mechanism_claim_supported` are not the
same decision. A top-level blocked human review cannot promote either gate,
even if a nested record claims approval.

### Hypothesis exploration

A reviewer may mark a novel edge exploration-eligible even when the finalized
literature record says no direct precedent was found. Eligibility requires an
unblocked reviewed edge, exact atom/charge/state bookkeeping, complete
scientific and hypothesis review, explicit reviewer/rationale/timestamp, no
unresolved blocker, and explicit resolution of every known contradictory
record for that exact edge/channel.

The output records absence of direct precedent as
`novel_hypothesis_no_direct_precedent`. That gap does not itself block
exploration. A known unresolved contradiction or scientific bookkeeping defect
does block it.

### Mechanism-claim support and validation

Claim support requires source-located direct evidence, exact applicability,
`mechanism_support` bounded use, an explicit reviewed support decision, no
unresolved blocker and explicit resolution of every contradictory record for
the exact edge/channel. Analogy, internal rationale and absence of precedent
remain conditional or unsupported.

This artifact never validates the target mechanism. Every record and summary
therefore retains `mechanism_claim_validated: false`, and the artifact retains
`mechanism_claim_validation_present: false`. Later independent experimental or
computational evidence can be classified and reviewed in a new immutable
revision, but never appears automatically after a calculation.

## TS-precedent and de novo handoff

`gaussian-ts-precedent-map/1` binds the exact mechanism-support artifact. A
literature precedent disposition opens candidate construction only when its
exact edge/channel is hypothesis-exploration eligible.

A novel exploration-eligible edge may instead use the separate
`de_novo_seed_plans` collection. A de novo plan has `source_precedent: null`
and `source_coordinates_used: false`; it cannot fabricate a literature
precedent or transferable coordinates. Only explicitly reviewed endpoint/QST,
relaxed-scan or structure-rebuild strategies are admitted, with exact hashed
prerequisite objects when required. This opens only the next offline candidate
construction stage. It does not create a geometry, validate a TS, select a
method or authorize calculation.

All mechanism-support and TS-precedent outputs unconditionally retain
`calculation_ready: false` and `no_submission_authorization: true`.

## Commands

```bash
python3 skills/auto-g16-reaction-workflow/scripts/mechanism_support.py build \
  mechanism-network.json knowledge-snapshot.json literature-evidence.json \
  --review mechanism-support-review.json --output mechanism-support.json

python3 skills/auto-g16-reaction-workflow/scripts/mechanism_support.py validate \
  mechanism-support.json
```

Both commands use only the Python standard library, perform no network or live
action, reject duplicate/non-finite JSON and unknown fields, and refuse output
overwrite.
