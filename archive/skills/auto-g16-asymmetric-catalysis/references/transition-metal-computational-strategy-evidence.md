# Auto-G16 Transition-Metal Asymmetric-Catalysis Strategy Evidence

Status: bounded literature evidence and software-design input, reviewed
2026-07-15. This file is not a protocol menu, method recommendation, active-
catalyst assignment, TS validation, or calculation authorization.

## Search scope and limitations

The manual search used exact DOI/title, transition-metal asymmetric-catalysis,
TS-conformer ensemble, spin-crossing/MECP, multireference-diagnostic, and
low-frequency-thermochemistry lanes. Publisher pages and lawful open copies at
ACS, RSC, Wiley, Purdue and UNT were reached. Crossref and OpenAlex were not run
as a reproducible retrieval in this task, and the search interface did not emit
a stable raw-result corpus; raw and deduplicated record counts are therefore
not available. No claim of exhaustive coverage or absence is permitted.

The records below were deduplicated by DOI. Primary article or SI evidence is
used for system-specific statements. Review-style sources are used only for
terminology and discovery. Every transfer to a new reaction remains an analogy
unless the exact catalyst state, elementary step and stereochemical question
match.

## Source-located evidence

| Source | Evidence class and locator | Source reports | Auto-G16 implication, not a default |
| --- | --- | --- | --- |
| Guan, Ingman, Rooks and Wheeler, “AARON: An Automated Reaction Optimizer for New Catalysts,” *J. Chem. Theory Comput.* 2018, DOI [10.1021/acs.jctc.8b00578](https://doi.org/10.1021/acs.jctc.8b00578) | workflow analogy; abstract and publisher SI listing | Asymmetric-catalysis prediction can require hundreds of TS/intermediate optimizations; the SI supplies coordinates, energies and XYZ TS structures. The paper includes transition-metal applications. | Candidate generation needs stable state/channel/conformer identifiers and retained source coordinates. Automation does not establish state correctness or TS validity. |
| Laplaza, Sobez, Wodrich, Reiher and Corminboeuf, “The (not so) simple prediction of enantioselectivity,” *Chem. Sci.* 2022, DOI [10.1039/D2SC01714H](https://doi.org/10.1039/D2SC01714H) | direct Rh/chiral-Cp asymmetric precedent; Methods 2.1–2.3, Figs. 1–2 and ESI | A coordination-constrained conformer pipeline generated 50 guesses per model, refined many distinct TS conformers, verified relevant modes, and used channel-wise Boltzmann weighting. Flexible Cp rotation materially affected predicted er. | Explicit hapticity/coordination constraints, full conformer provenance, deduplication and ensemble aggregation are required. The paper’s method stack and numeric settings are not defaults. |
| Sharma *et al.*, “DFT and AFIR Study on the Mechanism and the Origin of Enantioselectivity in Iron-Catalyzed Cross-Coupling Reactions,” *JACS* 2017, DOI [10.1021/jacs.7b05917](https://doi.org/10.1021/jacs.7b05917) | direct Fe asymmetric precedent; abstract, prereactant-state discussion, TS probability table and EDA section | Multiple Fe oxidation/ligand states and off-cycle products were considered; MC-AFIR searched C–Fe/C–C paths; more than one low-energy TS contributed to the reported selectivity model; deformation/interaction analysis was interpretive. | Active-state inventory and elementary-step selection must precede TS search. AFIR is a distinct future strategy type, not an alias for the three currently modeled Gaussian seed strategies. EDA cannot replace coverage or TS evidence. |
| Liu *et al.*, “Borane/Transition Metal–Catalyzed Allenylic and Allylic Alkylation of Unactivated 2-Alkylbenzoxazoles,” *JACS* 2025, DOI [10.1021/jacs.5c13835](https://doi.org/10.1021/jacs.5c13835) | direct borane/Ni asymmetric precedent; publisher abstract and SI DFT section, cross-checked in `wang-group-computational-precedents.md` | The reaction uses cooperative borane/Ni catalysis; the SI reports six TSs for the stereodetermining allenylic step and discusses steric and C–H···F organization. | Cooperative borane/metal identity, binding mode and TS-topology dimensions must all be explicit. Six reported TSs do not prove complete state/conformer coverage for another reaction. |
| Green, Harvey and Poli, methane addition to group-6 metallocenes, *J. Chem. Soc., Dalton Trans.* 2002, DOI [10.1039/B111257K](https://doi.org/10.1039/B111257K) | elementary-step/spin-surface analogy; abstract and supplementary-coordinate listing | Singlet and triplet surfaces, MECPs and same-surface transition states were treated as different objects; the MECP could be the controlling barrier. | A spin-crossing path cannot be encoded as an ordinary single-surface TS/IRC. Surface identities and crossing evidence need a separate contract. |
| Chachiyo and Rodriguez, “A direct method for locating minimum-energy crossing points,” *J. Chem. Phys.* 2005, DOI [10.1063/1.2007708](https://doi.org/10.1063/1.2007708) | method evidence; abstract and method/application description | Introduces an MECP optimization method and applies it to an Fe spin-crossover complex with distinct structural changes. | “MECP required” is a blocker and future strategy class; it must not be silently converted to QST, scan or IRC. |
| Jiang *et al.*, “Multireference Character for 3d Transition-Metal-Containing Molecules,” *J. Chem. Theory Comput.* 2012, DOI [10.1021/ct2006852](https://doi.org/10.1021/ct2006852) | benchmark analogy; diagnostic analysis and identified pathological set | Multiple diagnostics (`T1`, `D1`, `%TAE` and spin contamination) provide non-equivalent evidence; single-reference failures occur in parts of the 3d set. | Store a system-specific diagnostic policy and all observed diagnostics. Do not infer acceptability from SCF convergence or one universal threshold. |
| Wang, Manivasagam and Wilson, “Multireference Character for 4d Transition Metal-Containing Molecules,” *J. Chem. Theory Comput.* 2015, DOI [10.1021/acs.jctc.5b00861](https://doi.org/10.1021/acs.jctc.5b00861) | benchmark analogy; abstract/results and repository record | Diagnostic behavior and proposed criteria differ between 3d and 4d datasets. | Metal-row and chemical-context provenance belongs in a reviewed diagnostic policy; 3d thresholds must not be copied to 4d systems. |
| Laplaza, Wodrich and Corminboeuf, “Overcoming the Pitfalls of Computing Reaction Selectivity from Ensembles of Transition States,” *J. Phys. Chem. Lett.* 2024, DOI [10.1021/acs.jpclett.4c01657](https://doi.org/10.1021/acs.jpclett.4c01657) | selectivity-model analogy; abstract, ensemble-processing examples and conclusion | Repeated/equivalent conformers and mixing interconvertible with noninterconvertible paths can qualitatively change selectivity predicted from the same TS set. | Deduplication, degeneracy and interconversion assumptions must be explicit. A Boltzmann TS ensemble is refused when a kinetic network is required. |
| Grimme, “Supramolecular Binding Thermodynamics by Dispersion-Corrected Density Functional Theory,” *Chem. Eur. J.* 2012, DOI [10.1002/chem.201200497](https://doi.org/10.1002/chem.201200497) | thermochemistry-method analogy; article thermodynamic procedure and SI | Introduces a modified/quasi-RRHO treatment in a large, flexible binding context and separates energetic/thermal contributions. | Low-frequency treatment must be an explicit protocol choice and sensitivity dimension. The paper is not transition-metal-asymmetric validation and supplies no default cutoff for this Skill. |

## Common model families to expose as reviewed choices

The literature supports exposing these model families as explicit, mutually
auditable choices. It does not support selecting one automatically.

1. **Chemical-state models:** full catalyst versus a documented truncation;
   alternative ligand count, hapticity, counterion/contact-ion pair, explicit
   solvent/additive, aggregation and substrate-binding states.
2. **Electronic-state models:** separately identified oxidation/charge/
   multiplicity/wavefunction states; same-surface TS models; and a distinct
   MECP/crossing model when surfaces communicate.
3. **TS search models:** reviewed TS-like guess/Hessian, atom-correspondent
   QST2/QST3 endpoints, reviewed relaxed scans, and separately typed future
   AFIR/string/NEB/crossing strategies.
4. **Coverage models:** state × channel × binding mode × catalyst/substrate
   conformer × approach topology × ion-pair/additive placement × electronic
   state. Symmetry, duplicate and degeneracy decisions retain provenance.
5. **Selectivity models:** lowest-TS-only sensitivity; Curtin–Hammett/TST
   ensemble for rapidly equilibrating comparable states; or a kinetic network
   for slow interconversion, reversibility, multiple controlling steps or
   communicating catalyst states.
6. **Interpretation models:** distortion/interaction, activation strain, EDA,
   NCI or population analysis only after comparable ensemble evidence exists
   and after fragments/populations are explicitly defined.

## Fields added to the M2b observation boundary

The bounded implementation records exact candidate/template/log hashes,
charge/multiplicity records, atom order, terminal markers, raw frequency facts,
`S**2` before/after-annihilation text, an explicit stability-message flag, and
initial/final distances for already declared coordination contacts.

It deliberately does not:

- calculate or accept oxidation state, d-electron count or electron parity;
- assign a wavefunction, spin surface or multireference diagnosis;
- infer coordination distance windows, hapticity or ligand retention;
- infer method/basis/ECP/relativity/solvent or thermochemistry policy;
- accept a mode, TS, IRC, MECP, endpoint or selectivity claim; or
- create an input, route, checkpoint, server project or execution handoff.

Those omissions keep the broader `metal_m2_offline_runtime_contract` blocked.

## Fields added to the M2c input-observation boundary

The M2c observer binds an already existing local input to the exact candidate,
M2a template and M1 sidecar. It records only Link 0 text, normalized route text
and hash, charge/multiplicity, element order, a Cartesian-coordinate hash,
task-keyword text and the hash of uninterpreted trailing sections. It rejects
multi-step `--Link1--`, identity drift and checkpoint-only geometry ambiguity.

The observer does not turn a literature strategy into a route, parse a
basis/ECP block as scientifically suitable, select a three-tier protocol,
accept an input or validate a remote path. Even exact identity matching leaves
`input_acceptance_decision: not_granted_by_artifact`, scientific sections
blocked and all promotion/submission authority refused.

## M2d manual-decision boundary

The M2d sidecar separates wavefunction, coordination, mode and input decisions
so that one reviewed area cannot silently accept another. It binds the exact
M1, M2a, M2b and M2c artifacts. Section acceptance requires hash-bound manual
evidence appropriate to that section; missing evidence remains blocked and a
reviewer rejection is retained as a rejection rather than triggering a retry.

The literature above motivates the evidence categories but supplies no
automatic pass criteria. In particular, SCF convergence is not wavefunction
acceptance, stable distances are not coordination acceptance, one imaginary
frequency is not mode acceptance, and matching input identity is not protocol
or live approval. Four accepted synthetic sections still grant no top-level
scientific, input, mode, promotion, submission or execution authority.

## M1 sidecar boundary

The candidate-bound `gaussian-asymmetric-metal-scientific-review/1` sidecar
now records reviewer-supplied values and evidence locators without changing the
still-blocked design, template or candidate. Its synthetic complete fixture
tests the contract only and has
`metal_m1_scientific_review_status: not_satisfied_synthetic_fixture`.

The 2025 borane/nickel paper is retained as a real reaction anchor, but the
current repository has no exact atom-ordered candidate or contact inventory
for it. The source ceiling and unresolved electron, spin, wavefunction,
coordination, method and TS-design fields are recorded in
`wang-2025-borane-nickel-m1-gap-audit.md`. No common Ni model or literature
protocol is inserted as a default.
