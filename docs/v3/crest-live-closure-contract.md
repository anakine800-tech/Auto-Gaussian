# Auto-G16 V31 CREST completion and exact seed handoff

## Task and authority

Task `V31-CREST-LIVE-CLOSURE-01`, base
`b5a27f4cc77b9f2224dd81a0be5bb5e333a0fd58`, is an isolated v3 feature and
separately gated scientific smoke. The Owner's 2026-09-16 delegation explicitly
permits bounded implementation, independent review, exact delegated approval,
dedicated installation, one new CREST Attempt, native collection and independent
acceptance. It does not transfer the preceding xTB PR's publication/merge
authority. Delegated decisions identify the delegate and reviewed object; they
never purport to be the Owner personally approving an undisplayed object.

Status: **DESIGN CANDIDATE; implementation and live packets not yet frozen.**
The independent design review and unresolved source questions below must close
before implementation of their dependent behavior. This document records no
live qualification, approval, submission, or scientific result.

## Bounded outcome

One neutral closed-shell n-butane CREST 3.0.2 iMTD-GC smoke may consume the exact
native-captured, independently accepted xTB optimized XYZ from the preceding
Attempt. The original xTB Attempt, snapshot, approvals, receipt, captures,
results and databases retain their original identities. No xTB recomputation.
The new CREST input is byte-for-byte the captured geometry, with the same
ordered atoms, charge and GFN model. Chemical connectivity is reviewed before
approval; element counts alone do not prove the species identity.

Success requires a qualified exact executable/environment, one authorized
submission, native output capture, provenance replay and independent review.
It establishes only this finite sampling run. It establishes no exhaustive
search, global minimum, DFT energy, frequency, thermochemistry or reaction claim.

## Versioned semantics

Retain all strict xTB/CREST v1/v2 and xTB receipt v3 bytes and identities,
including the existing publisher source and qualification tuple. Add only:

- CREST adapter version 3, explicitly selected by completion mode; the default
  CREST adapter remains version 2.
- CREST completion receipt `/2`, requiring program `crest`, adapter version 3,
  operation `imtd-gc` and `receipt-on-absence-v1`. Receipt `/1` remains xTB-only.
- CREST publisher qualification `/2`, rendering material `/3`, prebinding `/4`,
  scheduler `/4`, and pilot-deployment `/2`, with exact tuple rejection. Q must
  bind actual CREST and all required runtime identities; an xTB Q cannot qualify
  CREST. No relabeling of the old runtime's `xtb` field.
- A dedicated xTB-to-CREST seed handoff `/2` consuming native terminal-success
  proof `/2` after reclosure of the source result/capture/assessment and complete
  exact xTB snapshot. Existing handoff `/1` and strict proof consumers continue
  rejecting receipt success. No proof is translated or downgraded to `/1`.
  The source revalidator is strictly read-only under the existing guard. It
  checks current persisted history/bundle and rejects conflicts without calling
  the mutating replay/reducer or appending an assessment. All source-store
  bytes, row counts and states remain unchanged on success and every rejection.

The new adapter retains explicit GFN model, charge/UHF, MTD length, CREGEN
energy/RMSD/temperature, normal-MD temperature and engine-managed stochastic
policy. It fixes ordered `-v3 -cross -nozs` semantics: CREST 3.0.2 `-cross`
enables automatic Z sorting; the following `-nozs` disables atom reordering.
No seed/retry/recovery method is invented. SamplingProfile must explicitly
bind adapter 3 and the new fixed atom-order semantics; old profiles and their
identities remain unchanged.

## Completion and outputs

The new required exact files are `crest.out`, `crest_best.xyz`,
`crest_conformers.xyz` and `crest.energies`. There are no optional outputs in
this narrow version. Capture limits remain explicit and bounded.

Program exit 0 is necessary but insufficient. Provenance-valid final evidence
must include exactly the version-qualified `CREST terminated normally.` line
after `CREST iMTD-GC SAMPLING`, `Meta-Dynamics Iteration 1`,
`MTD Simulations done` and `Final Ensemble Information` in that order,
and a nonempty conformer trajectory. Match complete lines after stripping
whitespace and the source's decorative box characters (`|`, `│`, `*`). Sampling
header, Final Ensemble Information and normal termination each occur once.
Between header and Final, allow one or more complete cycles, each with one
Iteration 1 followed by one MTD Simulations done; wrong ordering or incomplete
cycles reject. This preserves the source's legitimate MAINLOOP restart after
rotamer/GC improvement. Later numbered MTD iterations are permitted but do not
replace the first iteration marker.
A single conformer is allowed: neither
multiple frames nor a normal end marker alone proves sampling. The new adapter
uses only the modern, nonlegacy internal tblite GFN route; no ambient external
xTB lookup, legacy mode or caller PATH is added. Target qualification must
establish that the exact CREST binary supports this route.
Every XYZ frame must have the same
ordered element sequence and finite coordinates as the reviewed input. Best
geometry must match the first conformer. All energies must be finite, ordered
and consistent with the version-qualified energy writer and trajectory
cardinality. The Hartree comments have eight decimal places and relative
kcal/mol energies three; compare using Decimal with the source conversion
`627.50947428` and tolerance `0.0005 + 0.00000001 * 627.50947428` kcal/mol.
Both sets must be nondecreasing; relative energies start at zero and indexes
are exactly 1 through frame count. No arbitrary scientific-energy tolerance
is introduced. Coordinates and best/first comment match at emitted precision.
Missing required data is `output-incomplete`; malformed or inconsistent data
is `output-invalid`; either fails the Attempt after provenance is established.

Reuse existing exact scheduler-absence bracketing, receipt/input/output hash
closure, no-follow stat/fetch/restat, dual-store audit, bounded capture,
assessment persistence and zero-wire replay. Scheduler absence alone is not
success. Receipt unreadability or provenance drift remains UNKNOWN and grants
no retry. Strict success consumers remain isolated from receipt evidence.
Core execution success is distinct from output chemical acceptance. The
independent final reviewer checks every retained frame/best for C4H10,
single-fragment n-butane connectivity, carbon-chain and attached-hydrogen
identity, with no fragmentation or constitutional change. A failed chemical
check is retained as negative evidence and prevents scientific handoff, without
rewriting the execution history or creating a ConformerEnsemble implicitly.

## Execution, retention and approval

The new installation must be finite and source-bound. Before any real mutation,
display the exact target, current profile/program identities, reviewed chemical
identity and seed hash, complete scientific controls, simple resources
(8 cores, 12 GB, explicitly bounded walltime), exact fresh Attempt/snapshot,
one-submission side effects, required outputs, stop conditions and retention.
Independent review precedes delegated approval. The product Scientific,
finite Batch and exact Operational gates remain mandatory.

Use the existing product-bound Project only after current re-attestation, and
a fresh Attempt directory; no implicit Project adoption or overwrite. A new
limited local operational environment retains all approvals and source pins.
UNKNOWN is reconciliation-only. No automatic retry, replacement Attempt,
qdel, file deletion, cleanup or mutation of the old xTB stores is authorized.
The program's own intrinsic temporary-file behavior must be disclosed in the
exact packet; operational cleanup commands are excluded.

## Scope and reuse

Allowed code: `auto_g16/execution/program.py`, `program_runtime.py`, private
completion/CREST/handoff modules; the smallest private Transport tuple checks
in `auto_g16/transport/_program_rtwin.py`; private conformer profile/alignment
validation; and the existing fixed pilot Controller if a versioned tuple needs
an exact dispatch. Add focused tests and authority/context documentation.
No new public execution record, Core/Approval/Result schema, SQLite DDL,
Transport operation, generic shell/env extension, alternate backend, Gaussian,
legacy scheduler parser, test selector or CI policy change.

Reuse disposition: existing R4 publisher lifecycle, descriptor-relative
publication, native collection/recovery, Controller approval replay and store
guards are WRAP/REUSE with separate CREST tuple selection. Existing strict
handoff remains unchanged; the receipt successor shares only pure exact-byte
checks. CREST output parsing is NEW because old adapters have no version-correct
completion closure. No redevelopment of xTB/R4 or cross-process recovery.

## Required independent evidence

1. Historical spec/snapshot/source goldens and strict consumer rejection.
2. Exact argv/profile/input/resource invalidation, including `-cross -nozs`
   ordering and illegal version/mode combinations.
3. Receipt/Q/material/source/deployment cross-version and cross-program
   rejection; missing/current-drifted runtime identity yields zero effects.
4. Exit nonzero/signal, missing normal termination, missing/empty outputs,
   malformed trajectory, changed atoms, nonfinite/unsorted/wrong-cardinality
   energies, best mismatch and forged hashes fail at the correct boundary.
5. Native synthetic submit/collect/zero-wire replay and dedicated handoff `/2`
   bind the exact source capture, proof, model/charge, profile and destination.
6. Exact current qualification and dedicated installation review precede one
   real Attempt. Independent acceptance binds the actual job/capture/result
   and replay evidence; old xTB tests do not qualify CREST.

## Version-qualified source closure

Official CREST tag v3.0.2 resolves to
`af7eb9927e2b36e24b14055f9eba3bea5be0014e`. Source references:
`src/crest_main.f90`, `src/confparse.f90`, `src/legacy_wrappers.f90`,
`src/cregen.f90` in <https://github.com/crest-lab/crest/tree/af7eb9927e2b36e24b14055f9eba3bea5be0014e>.
`src/classes.f90:547` defaults `legacy=false`;
`src/legacy_wrappers.f90:138` dispatches modern iMTD-GC;
`src/calculator/calc_type.f90:1183` chooses internal tblite for GFN1/2;
`src/algos/search_conformers.f90:63,249` supplies sampling/final markers.
`src/cregen.f90:2160,2562` supplies the best/ensemble and relative energy
writers, using `src/crest_pars.f90:23` for the conversion constant.
`src/strucreader.f90:1602` writes coordinates to ten decimal places.
`src/confparse.f90:1077,2178` proves the ordered `-cross -nozs` requirement.
These source facts do not qualify an installed binary or constitute live
evidence. The complete exact source acquisition and independent audit are
retained in the operational evidence dossier outside Git.
Before binary qualification, source tracing must close MTD, multilevel
optimization, rotamer MD and `crest_newcross3` to internal calculator dispatch;
an unqualified external fallback is a stop, never permission to add PATH.
