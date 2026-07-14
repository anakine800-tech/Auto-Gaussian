# Transition-metal scientific-support design

This is a design and refusal contract. It does not extend the execution scope
of `gaussian-ts-irc`, generate Gaussian routes, or authorize a metal job.

## Boundary

Every metal/chiral-ligand or metal/chiral-boron cooperative state remains:

```text
runtime_support_status: unsupported_requires_extension
submission_decision: refused
calculation_ready: false
no_submission_authorization: true
```

The offline design command is:

```bash
python3 skills/gaussian-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  design-metal-support STUDY.json --output METAL-SUPPORT.json
```

It inventories questions and gates only. It never creates a route, Gaussian
input, PBS plan, server directory, or execution handoff.

## Required scientific layers

### Oxidation state and electron count

Record formal oxidation state per metal, d-electron count, total charge,
electron parity, ligand charge conventions, and alternatives involving
non-innocent ligands. Treat assignments as reviewed hypotheses, not facts
deduced from an element symbol.

### Spin-state space

List every chemically credible multiplicity for each coordination/oxidation
state. State how relative spin-state energies will be referenced. Identify
whether spin crossover or a minimum-energy crossing could enter the mechanism.
Never use singlet as an automatic default.

### Wavefunction checks

Specify restricted, unrestricted, restricted-open-shell, or broken-symmetry
hypotheses explicitly. Require SCF stability evidence, `<S^2>`, spin-
contamination review, alternative broken-symmetry solutions when relevant, and
multireference diagnostics appropriate to the system. A converged SCF is not
by itself an accepted electronic state.

### Coordination chemistry

Audit coordination number and geometry, hapticity, ligand stoichiometry,
hemilability, agostic contacts, counterions, ion pairing, solvent/additive
occupancy, vacant versus associated states, and substrate binding face. Keep
each chemically distinct alternative in the candidate ledger or preserve a
reviewed exclusion.

### Method protocol

Review metal and ligand basis/ECP coverage, relativistic treatment, dispersion,
solvent, integration grid, SCF controls, and spin-state benchmarking. No Wang-
group literature setting or other precedent becomes a default.

## Extension acceptance gates

An eventual execution extension requires all of the following before any live
proposal can be considered:

1. reviewed chemical-state and coordination inventory;
2. reviewed oxidation/electron-count and spin alternatives;
3. explicit wavefunction and stability diagnostics;
4. reviewed method/basis/ECP/relativistic benchmark protocol;
5. offline parser, builder, negative, and refusal fixtures;
6. evidence that unsupported states cannot be promoted or submitted; and
7. separate review of the execution-layer boundary.

Until those gates exist and pass, a metal candidate is useful only as an
offline hypothesis and coverage record.
