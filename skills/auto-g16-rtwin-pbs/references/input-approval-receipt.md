# Auto-G16 generic exact input approval

`gaussian-input-draft-review/2` and
`gaussian-input-approval-receipt/1` are immutable, non-authorizing offline
artifacts. They are the input-review gate between protocol selection and live
approval; neither artifact creates a server directory or authorizes transport,
PBS, Gaussian, retry, cancellation or cleanup.

## Compatibility boundary

| Input family | `work_kind` | Generic receipt `/1` |
|---|---|---|
| Self-contained single-structure Cartesian SP or other non-Opt/non-Freq non-specialist job | `ordinary` | Supported |
| Self-contained Cartesian minimum optimization | `minimum` | Supported |
| Self-contained Cartesian single-guess TS Opt/Freq | `ts_pilot` or `formal_ts` | Supported; scientific maturity and exact action authorization remain separate |
| QST2/QST3 multi-structure raw syntax | TS kind | Blocked pending specialist raw-syntax owner audit |
| ModRedundant/scan input | `ts_scan` | `blocked_missing_specialist_input_approval` |
| IRC input | `irc_forward` or `irc_reverse` | `blocked_missing_specialist_input_approval` |
| `Geom=AllCheck`, `Geom=Check`, `Guess=Read`, `%oldchk` or other checkpoint-derived input | specialist kind | `blocked_missing_specialist_input_approval` |
| Endpoint reoptimization owned by a TS/IRC family | `endpoint_reopt` | `blocked_missing_specialist_input_approval` |
| Any `--Link1--`, multiple route sections, or repeated `Opt`/`Geom`/`Guess` keyword | any | Blocked pending a complete multi-route owner review |

Do not use `gaussian-candidate-input-handoff/1` as a universal approval. That
artifact belongs only to the reaction-workflow adapter's restricted
closed-shell main-group single-guess TS/Freq contract.

## Exact bindings

The review binds the exact protocol-options and protocol-selection file and
payload hashes, selected option payload, and a non-empty subset of selected
task indices and profile IDs consumed by this one input. Every consumed task
must replay exactly from the same selected option, with no duplicate index.
The reviewer explicitly confirms how the exact route maps to the selected
method, basis, solvent, SCF and task evidence. The review also binds the exact
route, resources, charge, multiplicity, atom inventory and input SHA-256.
Task evidence uses deterministic predicates rather than reviewer-chosen route
substrings: single-guess TS requires both `Opt(TS...)` and `Freq`; minimum
requires a non-TS/non-scan `Opt`; ordinary rejects both optimization and
frequency families. Both `Keyword=Value` and `Keyword(Value,...)` spellings are
recognized. The protocol formula is parsed to complete element counts and must
match the input inventory. This is not an automated constitutional-isomer or
stereochemical identity proof; exact human input review and the exact input
hash remain the identity boundary.

A multi-stage option may legitimately render more than one input. Each review
binds only its own task/profile subset and records
`protocol_family_completion: false`; it never claims that other Opt/Freq/SP
inputs are approved or that the whole family is complete. A separate
versioned family manifest is required wherever whole-family coverage matters.

The receipt replays all owner artifacts through public protocol validators,
reconstructs the mapping and exact input, and records its own immutable payload
hash. It has `single_exact_input_only: true`,
`protocol_family_completion: false`, `calculation_ready: false`, and
`no_submission_authorization: true`.

## Offline commands

Prepare the human-reviewed JSON draft with `payload_sha256: null`, then publish
it without overwrite:

```bash
python3 scripts/gaussian_rtwin_pbs.py finalize-input-review review-draft.json \
  --output input-review.json
```

Build and replay the generic receipt:

```bash
python3 scripts/gaussian_rtwin_pbs.py build-input-approval job.gjf \
  --protocol-options options.json \
  --protocol-selection selection.json \
  --input-review input-review.json \
  --receipt-id reviewed_job_input_v1 \
  --output input-approval.json
python3 scripts/gaussian_rtwin_pbs.py validate-input-approval input-approval.json
```

Finalization uses same-directory durable temporary output and atomic
no-clobber publication. An existing or concurrently created destination fails;
immutable review/receipt files are never replaced in place.

For `submit`, transport first captures one unique durable non-symlink snapshot
of the source input. Input approval, scientific authorization and live `/3`
are replayed against that snapshot; staging copies only those captured bytes.
The staged input facts and every upload-file hash are rechecked before the
first network action and again before transfer. Approval receipt file hashes
are taken from the same stable read used to validate their JSON, preventing a
validate-then-rehash substitution.
