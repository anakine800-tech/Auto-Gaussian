# TS–Freq–IRC protocol contract

## Manifest: `gaussian-ts-irc-workflow/1`

Record a workflow ID, PBS-safe prefix (1–15 letters/digits/underscores), source paths and SHA-256 values, input identities/formula/components, charge, multiplicity, atom count, explicit shared atom map, intended forming/breaking/transferring pairs, entry mode, all complete approved routes, parsed method/basis/dispersion/solvent/grid/SCF fields when available, temperature/standard state/low-mode policy, per-stage resource tier, expected Gaussian stage counts, review decisions, project names, job IDs, and parent/child artifact hashes.

The complete TS/Freq, forward-IRC, reverse-IRC, endpoint Opt/Freq routes are user-supplied protocol values. Never use a placeholder or convert a route between stages implicitly. Confirm exact G16 IRC keyword support for the installed revision before generating a real input.

Record the Gaussian revision parsed from the completed TS log in every IRC plan and reject a manually supplied mismatch. The forward route must explicitly contain the forward direction keyword and not the reverse keyword; the reverse route must satisfy the converse. Reject swapped or directionless routes even when their remaining keywords are identical.

For QST2/QST3, validate atom correspondence locally but keep raw multi-structure input generation disabled until a known-good input from the installed G16 revision is available. A local Cartesian parser cannot establish whether a particular separator or repeated charge/multiplicity block will be accepted by Gaussian. On `End of file in ZSymb`, preserve the log and stop; obtain a verified input example rather than using the scheduler as a syntax test loop.

## Results

`gaussian-ts-freq-result/1` holds termination/error evidence, stationary-point status, energy, frequencies, raw imaginary count, parsed displacement vectors, final geometry, candidate status, mode-review status, hashes, and diagnostics. Exactly one negative frequency makes `first_order_saddle_candidate` true only when normal/stationary/frequency evidence is also present.

`gaussian-ts-mode-review/1` is an immutable evidence artifact bound to the TS-result SHA-256. Its plus/minus XYZ files are immutable visualization sources. On RTwin, derive a hash-bound, non-runnable MOL preview with `gaussian-view-rt-win`; never disguise an XYZ displacement as a runnable Gaussian input, and never accept process-start evidence without document-level load confirmation. `gaussian-ts-mode-decision/1` is a separate, explicitly confirmed record bound to both the review and TS-result hashes. Never mutate the TS result or mode-review artifact to record acceptance. A changed source hash invalidates the decision.

For a same-input `Opt ... Freq` calculation, parse only a post-terminal fetch. The Opt stage can write one normal termination before the Freq stage begins; a live Gaussian process takes precedence over that intermediate marker.

`gaussian-irc-plan/1` is a local submission plan, not a job. It records the verified G16 revision, direction, reviewed TS-result hash, accepted mode-decision hash, checkpoint hash, supplied route, resource tier, and fresh project. It must be handed to the PBS layer only after G3 approval.

`gaussian-checkpoint-geometry-audit/1` binds a non-symlink checkpoint basename and SHA-256 to the explicit reviewed TS input, completed TS log, TS result, imaginary-mode displacement indices, mode review, and accepted decision. Require identical charge/multiplicity and one-based atomic-number order across the explicit input, final log orientation, result geometry, and displacement table. State explicitly that this provenance audit does not decode the binary checkpoint.

`gaussian-allcheck-input-manifest/1` accompanies a coordinate-free continuation input of the same stem. Require `%oldchk` to match the audited checkpoint basename and hash, `%chk` to be distinct, and the route to contain the approved direction plus `RCFC Geom=AllCheck Guess=Read`. Put no title, charge/multiplicity line, or coordinates after the route. Reject changed input/checkpoint hashes, `ReCorrect=Never`, unresolved warnings, and atom-order records that are not contiguous and one-based.

`gaussian-irc-endpoint-audit/1` binds one direction's final completed point to the fetched IRC checkpoint, input, log, parsed result, and local job record. Require the declared final point, direction-specific completion, corrector convergence evidence for every expected point, normal termination, matching final log/result atom order and coordinates, and reviewed forming-bond distances. A reactant/product label is review evidence, not proof of a minimum.

For an endpoint continuation, reuse `gaussian-allcheck-input-manifest/1` with `continuation_kind: endpoint_opt_freq`. Require an approved route containing `Opt Freq Geom=AllCheck Guess=Read` and forbid IRC or TS optimization keywords. The `%oldchk` hash must match the endpoint audit and the input must contain no explicit molecule specification.

`gaussian-irc-component-proposal/1` binds a distance-based disconnected-component proposal to the endpoint-audit and IRC-result hashes. Restrict automatic detection to supported main-group organic elements and record the exact covalent radii, scale, proposed bonds, coordinates, formulas, and source atom indices. Mark it `calculation_ready: false`; never infer chemical identities, fragment charges, fragment multiplicities, or spin coupling.

`gaussian-irc-component-review/1` must bind the proposal SHA-256, record `decision: accepted` and `confirmed: true`, preserve each proposed atom partition exactly, and explicitly supply every identity, PBS-safe fresh project, integer charge, positive multiplicity, and a non-empty spin-coupling note. Require fragment charges to sum to the audited total charge.

`gaussian-irc-fragment-endpoint-plan/1` records the reviewed explicit Cartesian input hashes, atom maps, route, resources, and remote SDL directories. It grants no submission authorization. Forbid `IRC`, `Geom=AllCheck`, `Guess=Read`, and TS optimization keywords in fragment routes. `gaussian-irc-fragment-endpoint-validation/1` binds each fetched `job.json` to the planned input SHA-256 and requires completed stationary-point optimization, a complete frequency list, unchanged element order, and zero imaginary frequencies for every planned fragment. Label the energy sum as isolated-fragment electronic energy only; it is not a reaction Gibbs energy.

Final validation needs both complete IRC direction results plus endpoint Opt/Freq evidence. A connected endpoint uses one reviewed continuation. A disconnected asymptotic endpoint may use separately reviewed isolated fragments after preserving the failed or bypassed combined-supermolecule evidence and documenting why no finite-distance minimum is claimed. A failed IRC does not by itself disprove the stationary point; it means the intended connection was not established.

After an HPC first-point corrector failure, a one-direction AllCheck retry is diagnostic only. Do not increase `MaxCycle` again merely to prolong a diverging corrector sequence. A full `IRC=LQA`, EulerPC, DVV, or other integrator changes the numerical method and requires a separate explicit G3 approval; never use `ReCorrect=Never` as validation evidence.

## Resource tiers

Use `simple` (12 GB/8 cores), `general` (50 GB/22 cores), or `complex` (120 GB/44 cores). Job type never selects a tier automatically. Show `%mem`, `%nprocshared`, PBS request, and expected stage count before any submission.
