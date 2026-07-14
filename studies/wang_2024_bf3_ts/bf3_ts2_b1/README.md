# BF3-TS2-B1 preparation and in-flight run

Status: `exact_approved_live_job_running_pending_terminal_evidence`

The user selected the `standard` protocol with the `complex` resource tier
(120 GB, 44 cores). The version-controlled files preserve the offline,
hash-bound review artifacts. The exact rendered input later received a separate
live approval and was submitted once; that historical action does not turn any
artifact in this directory into standing authority for another submission,
retry, IRC, cancellation, or cleanup.

## Scientific identity

- Literature candidate: `wang2024_bf3_ts2_b1` / BF3-TS2-B1
- Formula and size: `C25H42BF3N4O3`, 78 atoms
- Proposed electronic state for exact review: charge 0, multiplicity 1
- Declared coordinate: C13-C21 bond formation
- Starting C13-C21 distance: 2.15133529 Å
- Reported featured imaginary frequency: -389.10 cm-1
- Required acceptance: a stationary point, all 228 harmonic modes, exactly one
  raw imaginary frequency, and an accepted hash-bound C13-C21 mode review

## Selected offline draft

- Route: `#p wb97xd/6-31g(d) scrf=(smd,solvent=toluene) opt=(ts,calcfc,tight,noeigentest,maxstep=5,maxcycle=100) freq int=ultrafine scf=(tight,xqc,maxcycle=128)`
- Resources: `%mem=120GB`, `%nprocshared=44`
- Input: `w24_bf3ts2_b1_s01.gjf`
- Input SHA-256: `0f26f244dfec97ad04fe757f7447b52bd39fb295af58b0ed463033a807ff37ad`
- Checkpoint basename: `w24_bf3ts2_b1_s01.chk`
- Coordinates: byte-for-byte numeric coordinate rows from the reviewed SI XYZ
- Offline audits: Cartesian audit and `single_guess` TS atom-map audit passed

The original offline manifest intentionally retains its pre-submission
non-authorization state. The separate workflow-status ledger records that the
approved action was exercised and that scientific acceptance remains pending.
The machine-local `live/` bundle preserves the input copy, checksums, PBS script
and job record but is ignored by Git.

The next gate is terminal evidence: confirm the final scheduler/process state,
fetch and parse the completed log, require a stationary point and exactly one
raw imaginary frequency, then perform a new hash-bound manual review that the
mode follows C13-C21 bond formation. No retry, BF3-TS2-B2, or IRC is implied.

`terminal-acceptance-plan.json` freezes these checks before the result is
known. It requires 228 harmonic modes for this 78-atom nonlinear system,
separates the literature -389.10 cm-1 reference from the acceptance criteria,
and defines stop-without-retry outcomes for zero/multiple imaginary modes,
wrong or ambiguous displacement, incomplete evidence, and error termination.
