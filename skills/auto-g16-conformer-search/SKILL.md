---
name: auto-g16-conformer-search
description: Plan and audit offline, dual-route conformer and noncovalent-complex candidate discovery from an exact reviewed R08 handoff, including explicitly state-bound main-group single-reference doublet or high-spin triplet V2 cases. Use for freedom analysis, preregistered Route A/B quotas, dependency diagnosis without execution, candidate legality audits, cross-matching, clustering, or immutable candidate-only handoffs. It does not infer chemistry or electronic state, select a reference or Gaussian method, execute external software, or authorize calculation.
---

# Auto-G16 Conformer Search

Operate only on an exact reviewed R08 handoff and an explicit configuration.
Treat every output as offline review evidence, never as permission to run a
search or calculation.

## Workflow

1. Read `references/workflow-contract.md` before planning a new search or
   interpreting a cross-validation result.
2. Confirm identity, atom map/order, connectivity, explicit hydrogens, charge,
   multiplicity, fragments, stereochemistry, state labels, and user-defined
   categories. V1 remains closed-shell-only. V2 may consume only an exact
   accepted main-group open-shell review for a single-reference doublet or
   high-spin triplet. Reject every other open-shell class, transition metal,
   excited state, multireference case, unknown coordination, or connectivity
   change.
3. Run `diagnose` to record dependency paths without executing or installing
   xTB, CREST, RDKit, spyrmsd, NumPy, SciPy, scikit-learn, MDAnalysis, or
   MDTraj. Missing capabilities remain blockers.
4. Run `analyze` to create the six-component freedom vector and heuristic
   route recommendations. Review the recommendations; they are not selected
   protocols.
5. Run `plan` only after exact A/B and A1/A2/B1/B2 weights, category quotas,
   shared xTB settings, constraints, seeds, and review flags are explicit.
   Plans contain inert argv templates and `execution_allowed: false`.
6. Obtain candidate observations outside this Skill under separately approved
   conditions. Run `audit` to compare every candidate against the reviewed
   state. Keep collisions, graph/state changes, mapping drift, transfers,
   dissociation, and optimization failures in the negative-evidence ledger.
7. Run `crosscheck` on the exact plan, candidate set, and ledger. Deduplicate
   within each route, match A/B basins, cluster route-unique structures, choose
   medoids, and queue ambiguous or symmetric cases for independent backend
   review. Never merge different category labels automatically.
8. Run `handoff` only after human review of selected medoids. The handoff stays
   `candidate_only: true`, `calculation_ready: false`, and
   `no_submission_authorization: true`.
9. For V2, preserve one identical structure-graph hash, atom-order hash,
   charge, multiplicity, state family, and accepted-review payload binding
   through R08, request, plan, every candidate member, ledger, ensemble, and
   handoff. Reject mixed states. Never rank across states, combine Boltzmann
   populations, or infer a ground state. Block unresolved fragment spin
   coupling.
10. Treat the first downstream purpose as minimum discovery. Gaussian Opt/Freq
   must accept the relevant reactant and product minima before any formal TS
   family consumes conformer evidence. A TS conformer may be derived only from
   an accepted reactant-minimum lineage recorded by the reaction-workflow
   scientific-maturity gate.

## Commands

```bash
python3 scripts/conformer_search.py diagnose request.json --output dependencies.json
python3 scripts/conformer_search.py analyze request.json --output freedom.json
python3 scripts/conformer_search.py plan request.json --output search-plan.json
python3 scripts/conformer_search.py audit search-plan.json candidates.json --output validity-ledger.json
python3 scripts/conformer_search.py crosscheck search-plan.json candidates.json validity-ledger.json --output ensemble-manifest.json
python3 scripts/conformer_search.py handoff ensemble-manifest.json --review review.json --output candidate-handoff.json
```

All writers refuse overwrite. Use new output paths and an explicit
`supersedes` binding for a new revision.

## Boundaries

- Do not guess missing chemistry, methods, atom mappings, category labels, or
  constraint semantics.
- Do not infer multiplicity, state family, wavefunction reference, protocol,
  fragment spin coupling, or cross-state ordering.
- Do not mix force-field, xTB, annealing, or route-weight values into final
  thermodynamic ranking.
- Never report FF/xTB energies as formal barriers or use geometry-only face,
  angle or distance enumeration to promote a mechanism edge or formal TS.
- Do not execute argv templates or version probes from this Skill.
- Use `auto-g16-view-rt-win` for R08 preparation and visual review.
- Use specialist workflows for unsupported electronic-structure cases.
- Use `auto-g16-rtwin-pbs` only after separate exact Gaussian input and live
  approvals. This Skill grants none.

Read `references/schema-guide.md` when authoring or reviewing artifacts.
