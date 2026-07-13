# Scientific workflows

## Opt-Freq-single-point contract

- Start from one selected, audited Cartesian structure.
- Use one checkpoint local to the project and three Gaussian Link1 stages.
- Require the Opt route and single-point route to be shown and approved separately.
- Derive Freq from the Opt route only by replacing the Opt job keyword with Freq and adding `Geom=AllCheck Guess=Read`; allow an explicit approved Freq route instead.
- Record temperature and either `1atm` or `1M` standard state.
- Keep all three stages at the same approved memory and core tier unless explicitly overridden.

Execution continues between Link1 stages after Gaussian normal termination. Scientific validation occurs after the complete log is parsed. A minimum requires optimization completion, a stationary point, a complete frequency calculation, and zero imaginary frequencies. A single-point energy is reportable only after the third stage terminates normally.

## Composite thermochemistry

Report separately:

- frequency-level zero-point, energy, enthalpy, and Gibbs corrections;
- frequency-level summed electronic/thermal values;
- final single-point electronic energy;
- composite Gibbs energy = single-point electronic energy + frequency-level Gibbs correction;
- standard-state correction applied per independently treated species.

For `1M`, apply the ideal-gas per-species correction `RT ln(RT)` using `R = 0.082057366 L atm mol-1 K-1` inside the logarithm. At 298.15 K this is about `1.8943 kcal mol-1` per species. Reaction corrections depend on stoichiometry; never add one correction to an entire reaction without counting independently treated reactants and products.

Do not silently apply quasi-harmonic corrections. Report frequencies between 0 and 100 cm-1 so the user can choose an approved low-frequency treatment later.

## Conformer populations

Aggregate only workflow results that:

- have `workflow_success: true`;
- represent the same chemical species, charge, multiplicity, method stack, solvent, temperature, and standard state;
- were generated from distinct reviewed conformers rather than accidental duplicate jobs.

Calculate populations from the composite target-standard-state Gibbs energies. Treat force-field rankings only as a prescreen and never mix them with Gaussian Gibbs energies.
