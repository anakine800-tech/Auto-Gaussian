# Auto-G16 transition-metal asymmetric TS P0-P1 baseline

This directory records a reviewable offline baseline. It contains no Gaussian
input, protocol selection, PBS path, live approval or execution authority.

## P0 result

MOBH35 reaction 33 is the provisional first metal-smoke candidate. The lawful
CC-BY supporting archive provides 15-atom `start`, `TS` and `end` Cartesian
blocks (`Pt1 C1 N2 H11`). The diagnostics workbook reports the formula field
`CH11N2Pt(1+)` and candidate-specific T1, D1, FOD(TPSS), HOMO-LUMO-gap and
M-diagnostic observations. Those values are observations, not acceptance
thresholds or an Auto-G16 method choice.

The one-based atom map and five-contact coordination inventory are frozen in
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

P1 is blocked before a real `gaussian-asymmetric-ts-candidate/1`. That existing
contract requires an integer multiplicity, while no candidate-specific R33
multiplicity source has been verified. Inserting singlet would violate the
non-inference gate. Consequently no real R33 M0, M2a or M1 sidecar is emitted.

`contract-probe/` shows that the existing M0/M2a/M1 builders and refusal chain
work using an explicitly synthetic fixture. It does not satisfy real M1 or M4.
The current status is therefore:

```text
P0: provisional_candidate_established_blocked
P1: blocked_before_real_candidate_and_m1
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

The exact blockers are enumerated in `baseline.json` and
`r33-candidate-inventory.json`. Highest priority is a candidate-specific
multiplicity/closed-shell assignment, followed by formal electron accounting,
spin-surface alternatives, wavefunction policy, reviewed chemical atom roles,
reaction-coordinate and endpoint identities, coordination windows,
candidate-specific mode evidence, method/ECP/relativity review, and the still
unimplemented metal M2/M3 boundaries.
