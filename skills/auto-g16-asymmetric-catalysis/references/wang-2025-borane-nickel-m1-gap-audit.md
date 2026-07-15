# Auto-G16 Wang 2025 Borane/Nickel M1 Gap Audit

Status: literature-anchored blocked draft, reviewed 2026-07-15. This document
is not a metal-support design, M1 scientific-review source, protocol proposal,
active-catalyst assignment, Gaussian input or calculation authorization.

## Bounded source

Liu *et al.*, “Borane/Transition Metal–Catalyzed Allenylic and Allylic
Alkylation of Unactivated 2-Alkylbenzoxazoles,” *J. Am. Chem. Soc.* 2025,
147, 40799–40806, DOI
[10.1021/jacs.5c13835](https://doi.org/10.1021/jacs.5c13835).

Publisher locators used in this audit:

- main-article abstract for the reported borane/nickel cooperative asymmetric
  allenylic alkylation and the separate borane/palladium extension;
- the publisher Supporting Information listing for
  `ja5c13835_si_001.pdf`, described as containing experimental details,
  characterization, HPLC, DFT calculations and NMR; and
- the SI computational-method paragraph and stereodetermining-TS discussion
  previously verified in `wang-group-computational-precedents.md`. The prior
  audit did not retain a page-indexed raw SI corpus, so no finer page locator is
  claimed here.

## Source-reported facts usable as evidence only

- The reported asymmetric allenylic reaction uses cooperative triarylborane
  and nickel catalysis; the borane activates the 2-alkylbenzoxazole so that
  triethylamine can deprotonate it.
- The verified SI record reports Gaussian 16 Rev. A.03; geometry optimization
  and frequencies at PBE0-D3(BJ)/def2-SVP; IRC; thermal treatment at
  283.15 K with Shermo 2.6 and a Grimme harmonic/free-rotor interpolation; and
  PBE0-D3(BJ)/def2-TZVP single points with SMD(dichloromethane).
- The SI reports six transition structures for the stereodetermining allenylic
  step. Its discussion interprets the lowest structure through steric
  organization and C–H···F contacts.

These facts describe the published model only. They do not select a method,
basis, solvent, thermochemistry treatment, TS strategy or active state for a
new calculation.

## M1 sections and current disposition

| M1 section | Source-grounded content | Required disposition |
| --- | --- | --- |
| electron accounting | A nickel-containing computed TS model is reported. | Blocked: this audit has no exact candidate-bound ligand-charge convention, formal Ni oxidation-state review, d-electron count, total valence-electron count, parity review or non-innocent-ligand alternative record. |
| spin/surface | The verified method summary does not establish a reviewed multiplicity inventory. | Blocked: total charge/multiplicity, credible alternative multiplicities, common spin reference, single-surface decision, spin-crossover relevance and MECP relevance require candidate-bound review. |
| wavefunction | A DFT method is reported for the published structures. | Blocked: restricted/unrestricted/RO/broken-symmetry hypothesis, stability policy, expected `S(S+1)`, contamination rule, occupation inspection, alternative solutions and system-specific multireference diagnostics are not established by this audit. |
| coordination | The paper discusses a chiral nickel/borane-bound organization and C–H···F contacts. | Blocked: the exact model atom order, Ni coordination number/geometry, ligand count/denticity/hapticity, substrate contacts, counterion/solvent occupancy, associated/dissociated alternatives and reviewed distance windows are not bound in repository artifacts. |
| method protocol | The exact literature stack above is source-reported. | Evidence only: per-element basis/ECP coverage, ECP core accounting, relativity, grid/SCF details and a new-system three-tier protocol selection remain unapproved. The literature stack is not a default. |
| TS/path design | Six stereodetermining TSs and general IRC use are reported. | Blocked: no repository candidate binds their atom map, channel definitions, exact coordinate changes, search-strategy provenance, mode-displacement review or candidate-specific bidirectional endpoint identities. |

## Why no real M1 artifact is checked in yet

`build-metal-scientific-review` requires exact SHA-256 bindings to a repository
metal-support design, M2a audit template, unsupported candidate and reviewer
source. This paper has not yet been transcribed into a reviewed study,
candidate atom map and coordinate/contact inventory. Creating placeholder atom
indices, charge, multiplicity, oxidation state or coordination contacts would
violate the non-inference gate.

The current honest outcome is therefore:

```text
metal_m1_review_contract: implemented_offline
metal_m1_scientific_review: pending_scientific_review
calculation_ready: false
scientific_acceptance_decision: not_granted_by_artifact
promotion_decision: refused
submission_decision: refused
```

## Minimum evidence needed to instantiate the real sidecar

1. a lawfully reviewed SI coordinate/model transcription with exact atom order,
   channel identity and candidate hashes;
2. explicit reviewer decisions for charge, multiplicity, ligand-charge
   convention, oxidation state, d count and electron parity;
3. credible spin/surface and wavefunction-diagnostic policies;
4. exact coordination/contact inventory with reviewer-supplied distance
   windows and alternative-state exclusions;
5. source-located per-element method/basis/ECP/relativity facts, separated from
   any later three-tier protocol proposal; and
6. a reviewed elementary-step class and one M2a strategy candidate, with
   execution selection still `not_selected`.

None of these items authorizes live SSH, PBS, Gaussian, deployment or a smoke
test.
