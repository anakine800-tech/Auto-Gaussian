# TS–Freq–IRC Skill design

Status: design contract; no live TS or IRC submission is authorized by this document.

## 1. Objective

Create a separate `gaussian-ts-irc` Skill that can prepare, submit, pause for scientific review, resume, retrieve, and audit a Gaussian 16 transition-state workflow through the existing RTwin/PBS transport.

The workflow must establish all of the following before reporting a validated reaction path:

1. the proposed transition structure converged to a stationary point;
2. a frequency calculation completed at the approved level of theory;
3. the structure has exactly one reported imaginary vibrational mode under the approved interpretation policy;
4. the displacement of that mode corresponds to the intended bond-making/bond-breaking motion;
5. forward and reverse IRC calculations completed from the reviewed TS;
6. the two IRC ends lead, after separately approved endpoint relaxation, to the expected reactant-side and product-side minima;
7. all artifacts, hashes, job IDs, protocol values, review decisions, and failures remain auditable.

This is a first-order saddle-point and connectivity workflow. It is not by itself proof that every chemically relevant pathway, conformer, bifurcation, solvent arrangement, or dynamical effect has been considered.

## 2. Layer boundaries

### New Skill: `gaussian-ts-irc`

Own:

- TS input-family preparation for an approved single guess, QST2 pair, or QST3 triplet;
- atom-order and atom-mapping validation across multi-structure inputs;
- TS/Freq result parsing and first-order saddle-point gates;
- imaginary-mode displacement extraction and review artifacts;
- forward/reverse IRC job-family construction;
- IRC path parsing, endpoint extraction, and endpoint identity comparison;
- workflow state, provenance, pause/resume gates, and final structured result.

Do not own:

- SSH credentials or transport implementation;
- PBS directory creation, upload, `qsub`, `qstat`, fetch, zombie cleanup, or `qdel` policy;
- generic ChemDraw conversion, conformer generation, or visible GaussView launch;
- asymmetric-selectivity aggregation.

### Existing dependencies

- Use `gaussian-view-rt-win` for reviewed Cartesian structures, stereochemistry, GaussView display, and any conformer handoff.
- Use `gaussian-rtwin-pbs` for preflight, immutable per-hop hashes, PBS execution, monitoring, retrieval, and the `/home/user100/SDL` boundary.
- Add generic checkpoint/dependency-file transport to the PBS layer only if TS/IRC requires it. Do not add TS scientific decisions to the PBS layer.

## 3. Non-negotiable boundaries

- Confine every server write and scratch directory to `/home/user100/SDL/<project>`.
- Use a new, empty, non-symlink server project directory for every PBS submission.
- Never delete or overwrite server project data.
- Require explicit approval before the first TS submission and again before IRC submission after mode review.
- Permit one automatic exact `qdel` only for a terminal scheduler zombie proven by the core Skill's repeated evidence gate after results are fetched. Require exact approval before cancelling a queued or running job; never infer cancellation permission from workflow approval.
- Do not automatically change a geometry, functional, basis, dispersion correction, solvent model, integration grid, SCF option, optimization keyword, IRC keyword, charge, multiplicity, memory, or core count.
- Do not automatically retry a failed stage.
- Preserve incomplete and failed artifacts as evidence.

## 4. Supported entry modes

Version 1 should support these modes separately rather than converting between them silently.

### A. Reviewed single TS guess

Require one audited Cartesian structure and an explicitly approved TS optimization route. Record how the guess was constructed and which internal coordinates are expected to form and break.

### B. QST2

Require reviewed reactant-side and product-side structures with identical atoms, atom order, isotope interpretation, charge, and multiplicity. Require an explicit atom mapping and reject ambiguous or reordered inputs.

### C. QST3

Require the QST2 pair plus a reviewed TS guess. Apply the same identity/order/mapping checks to all three structures.

GaussView 6 documents that QST2/QST3 use two or three structures and that the atoms must be identical with consistent ordering. The implementation must check this deterministically rather than relying only on the GUI.

Unsupported in version 1 unless separately designed: transition metals, excited states, broken-symmetry states, multireference cases, periodic systems, ONIOM, unusual isotope workflows, and pathways whose atom correspondence changes ambiguously.

## 5. Required protocol manifest

Create one immutable family manifest before submission. Proposed schema: `gaussian-ts-irc-workflow/1`.

Require at least:

- workflow ID and short PBS-safe project prefix;
- source file paths and SHA-256 values;
- expected reactant-side and product-side chemical identities;
- canonical isomeric representations where chemically meaningful;
- formula, total charge, multiplicity, component count, and atom count;
- explicit atom map shared across every structure;
- intended forming, breaking, or transferring atom pairs;
- entry mode: `single_guess`, `qst2`, or `qst3`;
- complete approved TS route;
- complete approved frequency route or an exact derivation rule;
- complete approved forward and reverse IRC routes;
- endpoint optimization and frequency routes;
- functional, basis/ECP, dispersion, solvent model, grid, and SCF options as separate parsed fields;
- temperature, pressure/standard state, and any low-frequency policy;
- selected memory/core tier for every stage;
- expected Gaussian stage count for every submitted input;
- review states and reviewer decisions;
- parent/child hashes and job IDs.

Do not create a universal research default. A smoke-test protocol may exist only when labeled test-only and must not be promoted to research use.

## 6. Execution graph and human gates

```text
reviewed structures + approved protocol
                  |
                  v
       atom mapping / input audit
                  |
                  v
             TS optimization
                  |
                  v
               frequency
                  |
                  v
    exactly one imaginary mode?
          | no                 | yes
          v                    v
        stop          mode displacement review
                               |
                         wrong/unclear -> stop
                               |
                          explicit approval
                               |
                  +------------+------------+
                  |                         |
                  v                         v
             IRC forward               IRC reverse
                  |                         |
                  +------------+------------+
                               |
                               v
                 extract and relax endpoints
                               |
                               v
              endpoint minima and identity audit
                               |
                               v
                    validated / inconclusive
```

### Gate G0: chemical and protocol approval

Show identities, atom map, intended coordinate changes, all routes, resources, and server project names. No submission before exact approval.

### Gate G1: TS input audit

Require finite Cartesian coordinates, no atom clashes, exact atom counts/order, matching charge/multiplicity, valid checkpoint basenames, and immutable hashes. For QST2/QST3, reject any mapping discrepancy.

### Gate G2: first-order saddle-point review

Require normal termination of TS optimization and frequency stages, stationary-point evidence, and exactly one reported imaginary mode. Report every negative frequency; do not silently discard a small negative value as numerical noise.

Generate a review artifact for the imaginary mode, preferably both:

- a machine-readable displacement table for every atom; and
- two displaced Cartesian structures or a GaussView-readable animation.

Automatically quantify how the reviewed mode changes the declared forming/breaking distances, but initially treat this as decision support rather than final chemical acceptance. Require explicit review before IRC submission.

### Gate G3: IRC approval

Show the reviewed TS hash, imaginary frequency, mode-review decision, exact forward/reverse routes, checkpoint dependency hashes, resources, and two new server directories. Submit neither direction if this evidence is incomplete.

### Gate G4: endpoint acceptance

Require both directions to terminate or label the workflow incomplete. Extract the last usable point from each direction, relax it with separately approved endpoint Opt/Freq jobs, and require zero imaginary frequencies for an accepted minimum. Compare connectivity, proton location, charge, multiplicity, component count, and stereochemistry with the expected two sides.

Do not silently swap forward and reverse labels. Assign chemical-side labels only after endpoint identity comparison.

## 7. Job-family and checkpoint provenance

Do not place the entire workflow into one uninterrupted Link1 chain because the imaginary-mode review must occur before spending resources on IRC.

Recommended job family:

- `<tag>_ts`: TS optimization plus frequency, with a reviewable checkpoint;
- `<tag>_if`: IRC forward;
- `<tag>_ir`: IRC reverse;
- `<tag>_ef`: forward endpoint Opt/Freq;
- `<tag>_er`: reverse endpoint Opt/Freq.

Every name must satisfy the PBS helper's 15-character project-name limit. The local family manifest links these separate projects.

For maximum provenance, fetch the TS checkpoint to the Mac, record its SHA-256, and explicitly restage the approved dependency into each IRC project. If a generic PBS dependency-file feature is added, it must hash every additional input on Mac, RTwin, and server and must still refuse non-empty server directories. Do not perform an unaudited server-side cross-project copy.

Use separate forward and reverse jobs so one direction can fail without obscuring the evidence from the other. Never submit a replacement direction automatically.

## 8. Parser and result contracts

### TS/Freq result

Proposed schema: `gaussian-ts-freq-result/1`.

Include:

- termination counts and error counts;
- optimization/stationary-point evidence;
- final TS geometry and energy;
- all frequencies, raw imaginary-frequency count, and thermochemistry;
- imaginary-mode atom displacement vectors;
- declared reaction-coordinate distance changes under plus/minus displacement;
- `first_order_saddle_candidate`;
- `mode_review_status`: `pending`, `accepted`, `rejected`, or `unclear`;
- diagnostics and immutable artifact hashes.

`first_order_saddle_candidate` is not equivalent to `validated_transition_state` until mode review and both IRC sides pass.

### IRC direction result

Proposed schema: `gaussian-irc-direction-result/1`.

Include:

- direction as submitted, route, checkpoint hash, and job ID;
- termination/error evidence;
- ordered path points, energies, and reaction-coordinate values;
- last complete geometry;
- path length and convergence/termination diagnostics;
- endpoint extraction status.

### Final workflow result

Proposed schema: `gaussian-ts-irc-result/1`.

Include:

- references to every child result and input hash;
- reviewed TS evidence and mode decision;
- both IRC outcomes;
- endpoint optimization/frequency outcomes;
- expected versus observed endpoint identities;
- whether forward/reverse labels were chemically assigned;
- final state: `validated`, `failed`, `incomplete`, or `inconclusive`;
- explicit reasons preventing validation.

## 9. Failure semantics

Stop and preserve evidence for each of these cases:

- TS optimization does not converge or lacks stationary-point evidence;
- frequency stage is absent, incomplete, or errors;
- zero imaginary modes: optimized minimum, not the requested first-order TS;
- more than one imaginary mode: higher-order saddle candidate;
- exactly one imaginary mode but displacement is wrong or unclear;
- input structures in QST2/QST3 do not share exact atom identity/order/mapping;
- either IRC direction errors, is truncated, or has no usable endpoint;
- both directions lead to the same minimum unexpectedly;
- endpoints do not match the declared reaction sides;
- endpoint optimization does not converge or retains an imaginary mode;
- protocol values differ between stages without an explicit approved reason;
- checkpoint, source, or transfer hash differs at any handoff.

Do not claim that a failed IRC invalidates the stationary point; report the narrower conclusion that the intended connection was not established by this workflow.

## 10. Resource policy

Inherit the existing tiers:

- simple: 12 GB / 8 cores;
- general: 50 GB / 22 cores;
- complex: 120 GB / 44 cores.

Treat job type and resource tier as separate decisions. TS/IRC does not automatically authorize the complex tier. Show exact `%mem`, `%nprocshared`, PBS request, and estimated number of submitted stages before approval.

During development, use this test ladder:

1. parser/unit fixtures only;
2. generated inputs and manifests with no network;
3. mocked RTwin/PBS transitions;
4. one separately approved small TS/Freq test;
5. mode review;
6. one IRC direction, then the other only after the first result is understood;
7. endpoint Opt/Freq;
8. one full closed-loop smoke workflow.

Select the real smoke-test reaction only after reviewing charge, basis requirements, known path behavior, and expected endpoints. Do not pick a charged SN2 or proton-transfer example merely because it has few atoms.

## 11. Offline test matrix

Add deterministic fixtures for:

- successful TS optimization with one imaginary mode;
- successful optimization with zero imaginary modes;
- higher-order saddle with two or more imaginary modes;
- malformed or missing mode displacement blocks;
- accepted and rejected declared-distance projections;
- QST2/QST3 atom-order mismatch;
- forward/reverse IRC success logs;
- incomplete and error-terminated IRC logs;
- endpoint identity match, side swap, same-side convergence, and mismatch;
- checkpoint hash mismatch;
- stage protocol mismatch;
- PBS queued/running/stale/zombie states inherited from the core Skill.

Offline tests must never invoke SSH, `qsub`, `qdel`, or Gaussian.

## 12. Implementation sequence

1. Define JSON schemas and state transitions.
2. Implement TS/Freq parser extensions, including displacement vectors.
3. Implement atom-map and multi-structure validators.
4. Implement TS input builders without submission.
5. Implement mode-review artifacts and explicit promotion.
6. Add hashed checkpoint/dependency handoff to the generic PBS layer if required.
7. Implement forward/reverse IRC builders and parsers.
8. Implement endpoint extraction, Opt/Freq preparation, and identity comparison.
9. Add the `gaussian-ts-irc` SKILL.md and UI metadata.
10. Run full offline validation.
11. Present a separately approved minimal real-test plan.
12. Only after the TS workflow is stable, design `gaussian-asymmetric-selectivity` against its structured outputs.

## 13. Decisions intentionally left open

Resolve these before implementation rather than guessing:

- exact approved TS, Freq, IRC, and endpoint routes for the first test;
- which single-guess/QST2/QST3 mode to implement first;
- the exact Gaussian 16 IRC force-constant and restart keywords supported by the installed revision;
- IRC step size, maximum points, coordinate system, and convergence options;
- whether a numerical imaginary-frequency tolerance is ever allowed;
- the initial mode-visualization interface;
- the first real smoke-test reaction.

## 14. Primary references used for this design

- Gaussian, Inc., *GaussView 6 Help*, section on transition-structure optimizations and QST2/QST3: https://gaussian.com/wp-content/uploads/dl/gv6.pdf
- Gaussian, Inc., *Vibrational Analysis in Gaussian*: https://gaussian.com/wp-content/uploads/dl/vib.pdf
- Gaussian, Inc., *Thermochemistry in Gaussian*: https://gaussian.com/wp-content/uploads/dl/thermo.pdf

The public Gaussian keyword pages were protected by an interactive verification screen during this design pass. Before coding exact IRC route construction, verify the keyword combinations against the documentation for the installed Gaussian 16 revision or an accessible official manual. Do not convert an unverified keyword assumption into a default.
