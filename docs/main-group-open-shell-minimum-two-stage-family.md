# Auto-G16 main-group open-shell minimum two-stage family

This offline, fail-closed family addresses
`gaussian_link1_combined_opt_freq_stable_parse_failure` in Gaussian 16 A.03
and prevents the same unsupported combined route prospectively.
It grants no retry, server, SSH, PBS, Gaussian, deployment, or cleanup authority.
The failed exact input remains superseded and must not be resubmitted.

Family handoff `/1` is retained only for an exact prior failed input and binds
that input's SHA-256. Prospective work uses handoff `/2`, records
`prospective_two_stage_minimum`, requires `prior_failed_input_sha256: null`,
and must not manufacture a failure lineage. Both versions retain the same
two-stage scientific workflow and downstream exact stage receipts.

## Required order

1. Build retry family handoff `/1` or prospective family handoff `/2`. Its
   `opt_freq` input contains Opt/Freq and no Stable. Its `stability` input
   contains `Stable=Opt Geom=AllCheck Guess=Read`, no Opt/Freq, `%oldchk`
   equal to stage 1 `%chk`, and a distinct output `%chk`.
2. Independently review stage 1 bytes and create only its receipt `/3`.
3. Accept stage 1 only with normal termination, stationary point, converged
   SCF, expected frequency count, zero imaginary frequencies, unchanged
   charge/multiplicity/U-or-RO, and S2 within policy. Bind the exact final
   checkpoint in checkpoint-binding `/1`.
4. Build stability manifest `/1`; independently review stage 2 and create its
   separate receipt `/3`. Only then may a human prepare a separate live `/5`.
5. Aggregate both results in family-acceptance `/1`. Stage 2 must terminate
   normally, contain stable-wavefunction text, preserve state, U/RO,
   method/basis and checkpoint lineage, and satisfy the S2 policy.

## Offline hash-chain tool

Run `skills/auto-g16-main-group-open-shell/scripts/open_shell_minimum_family.py`
with `build-family`, `approve-stage --stage opt_freq`, `bind-checkpoint`,
`build-stability-manifest`, `approve-stage --stage stability`, and
`accept-results`, in that order. Outputs are canonical, refuse overwrite, remain
`calculation_ready:false` and `no_submission_authorization:true`, and carry only
false action flags. The stability `.json` and exact checkpoint must sit beside
its `.gjf` for offline preflight. Do not commit `.gjf`, checkpoints, logs, or
real smoke artifacts.

## Exact live `/5` fields and stop conditions

Each stage's prospective `/5` must bind: project;
`/home/user100/SDL/<project>`; input SHA; exact route; memory; cores; charge;
multiplicity; work kind `minimum`; receipt `/3` file/payload/input hashes; owner;
workflow; family payload hash; stage; method; basis; U/RO reference; resource
tier; owner replay; and, for stability, the accepted final checkpoint SHA.
Authorizations are exactly create-directory/submit true and
retry/cancel/cleanup/delete false.

Stop before live action on any field/hash drift, symlink, missing artifact,
failed stage-1 evidence, checkpoint-generation uncertainty, missing
AllCheck/Guess=Read, reappearance of combined Opt/Freq+Stable, receipt/live
generation mixing, non-fresh project directory, metal, open-shell singlet,
broken symmetry, multireference, TS/IRC/scan/QST/Link1/maturity mixing, or any
network/server/scheduler/Gaussian/deployment/cancel/cleanup/delete action not
covered by a new exact authorization.
