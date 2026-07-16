# Auto-G16 transition-metal asymmetric TS P0-P1 baseline

This directory records a reviewable offline baseline. It contains no Gaussian
input, protocol selection, PBS path, live approval or execution authority.

## P0 decision

MOBH35 reaction 33 was the provisional first metal-smoke candidate. The lawful
CC-BY supporting archive provides 15-atom `start`, `TS` and `end` Cartesian
blocks (`Pt1 C1 N2 H11`). The diagnostics workbook reports the formula field
`CH11N2Pt(1+)` and candidate-specific T1, D1, FOD(TPSS), HOMO-LUMO-gap and
M-diagnostic observations. Those values are observations, not acceptance
thresholds or an Auto-G16 method choice.

The one-based atom order and five-contact geometric inventory are frozen in
`r33-candidate-inventory.json`. Distances support only these geometric
observations: C1-H7 shortens, Pt2-H7 lengthens and Pt2-C1 lengthens from start
through TS to end. Chemical step naming, mode identity and endpoint identity
remain pending source/reviewer confirmation.

MOBH35 Table 4 links R33 to ref 136, Iron, Lo, Martin and Keinan, JACS 2002,
DOI `10.1021/ja025667v`. The publisher abstract discusses H/D scrambling via
an eta2-CH-CH4 complex and separately names an `[(NH3)3PtMe(H)2]+` rigidity-test
model. The 15-atom R33 object contains only N2 and is therefore recorded as the
MOBH35 reoptimized reduced coordination state, not asserted to be that N3
model.

ACS Figshare article `3642549` additionally exposes primary-SI metadata for
dataset DOI `10.1021/ja025667v.s003`, file `5731353`
(`ja025667v_si_003.txt`, 46316 bytes, MD5
`9ec842c2537f2510f8a217dffff4e298`) under CC BY-NC 4.0. The download endpoint
was not obtained because of S3 DNS failure, so no content claim is made and no
SHA-256 is invented.

## P1 result

The bounded 2026-07-16 follow-up review retrieved the lawful 2022 primary
article full-text XML. Its methods section explicitly says that all systems in
the study are closed-shell and that the lowest closed-shell singlet SCF
solution was checked. R33 is retained in that study, so multiplicity 1 is now
recorded in `r33-p1-evidence-ledger.json` as a source-reported candidate, not
as an electron-parity inference or a scientific acceptance decision.

P1 remains blocked. The source does not enumerate R33 alternative
multiplicities or close oxidation/electron accounting, the wavefunction and
stability policy, coordination and ligand identities, chemical atom roles,
the elementary step and endpoints, mode/path evidence, or a prospective
method/ECP/relativity/solvent/thermochemistry/TS-strategy review.

The existing `build-metal-scientific-review` chain also requires a semantically
valid asymmetric-catalysis study, formal TS candidate, M0 design and blocked
M2a template. R33 is a non-asymmetric benchmark smoke object, and its sources
do not define two stereochemical/selectivity channels. Creating those objects
would require synthetic or inferred chemistry. Therefore the builder was not
invoked and no real sidecar was emitted. `r33-m1-blocked-review.json` records
that schema boundary and the exact gap ledger; it is not an M1 sidecar.

`contract-probe/` shows that the existing M0/M2a/M1 builders and refusal chain
work using an explicitly synthetic fixture. It does not satisfy real M1 or M4.
The current status is therefore:

```text
P0: provisional_candidate_established_blocked
P1: blocked_after_candidate_bound_evidence_review_no_real_m1
can_enter_P2: false
```

## Evidence search

The versioned literature intake and 25-lane plan were run only for the six DOI
seed lanes. OpenAlex returned six metadata payloads; Crossref was skipped
because no contact address was supplied. The screening ledger is discovery
metadata only. Separately, the Nature Communications Pd-hydride TS(S)/TS(R)
case has lawful public coordinates but is roughly 90-plus atoms per TS and is
not the minimal smoke. Wang 2025 borane/Ni remains the final two-channel
asymmetric target and is deliberately separate from R33.

## Next required evidence

The exact current blockers are enumerated in `r33-p1-evidence-ledger.json` and
`r33-m1-blocked-review.json`. Highest priority is formal electron accounting,
credible alternative spin surfaces, wavefunction/stability/multireference
policy, coordination and ligand review, chemical atom roles and endpoints,
mode/path evidence, and method/ECP/relativity review. The implemented P2-P4
offline engineering contracts remain blocked from real-case activation by P1.

`r33-p5-approval-package.json` is the exact fail-closed P5 planning package. It
is `planned_not_submitted`, not ready for live approval, and binds null protocol
options/selection, input draft/hash, resources and server project fields. The
only allowed server root is `/home/user100/SDL`; no directory was created. The
package authorizes no SSH, PBS, Gaussian, retry, IRC, cancellation, cleanup or
deployment action and is not itself submission authorization. The integrated
status remains indexed in `p0-p5-readiness.json`.

## Approved candidate-selection decision

`r33-first-metal-smoke-decision.json` formally rejects R33 only as the first
Auto-G16 metal smoke. It binds the exact P1 ledger, blocked M1 review, P5
package, and readiness lineage reviewed at the decision point. The decision is
not a criticism of the cited publications, MOBH35, the reaction, or R33's
general chemical value.

`replacement-candidate-selection.json` applies a stricter non-asymmetric
benchmark selection contract rather than fabricating two stereochemical
channels. The bounded review ranks a Pd(PHOX) TS20 literature object, a nickel
H2-pathway family, and a zinc-fluorination mechanism paper by proximity to a
reviewable candidate. None closes exact immutable coordinates, charge and
electronic-state assumptions, full species and reaction mapping, candidate-
specific mode/path evidence, complete protocol provenance, and the required
wavefunction-risk policy at once. Consequently no replacement candidate, real
M1 source, or real M1 sidecar was emitted, and no P5 authority exists.

The shortlist is not proof that no suitable published candidate exists. Its
claim ceiling is a bounded source screen and gap decision; it does not prove a
TS, reaction path, protocol suitability, chemical correctness, or live
execution readiness.

## Pd(PHOX) TS20 closure follow-up

`pd-phox-ts20-candidate-closure.json` corrects a material source-identity
error in the original shortlist: DOI `10.1021/acscatal.0c03282` is an
unrelated heterogeneous-catalysis article. The Pd(PHOX) TS20 article is JACS
DOI `10.1021/jacs.0c06243`, with correction DOI `10.1021/jacs.0c11706`.

The CaltechAUTHORS record lawfully supplies the matching SI PDF and energy
workbook. Their original SHA-256 values are recorded, while the ACS-copyrighted
objects remain temporary local review inputs and are not versioned. The closure
artifact freezes source-order coordinate-block hashes for the 82-atom
`(Si)-13` precursor and `(Si/chair/ax)-TS20`, plus the identity one-based atom
map. The SI contains all eight TS20 conformers, but no direct successor/product
coordinate block was established for the selected conformer.

The review remains blocked: exact charge, multiplicity, oxidation-state and
ligand-charge accounting, wavefunction/stability/S2/occupation/multireference
policy, one-based reaction-coordinate atoms, raw candidate mode displacement,
structured bidirectional IRC endpoints, explicit relativity, exact candidate
program version and TS localization strategy are not source-closed. No formal
candidate, real M1 source or sidecar was emitted, and P5 remains blocked.
