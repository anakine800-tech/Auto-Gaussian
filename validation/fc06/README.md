# Auto-G16 FC06 bounded Linux validation

This auxiliary lane runs eight synthetic process cases against product commit
`3116d1f1919eff164ef3593171d0ed7f42c778b5`; the harness verifies its tree and
original wrapper file/source hashes. It grants no production, scheduler,
chemistry, deployment or scientific authority and is not complete FC06 acceptance.

`config/auxiliary-workflows.json` registers exactly one FC06 workflow by path,
job/context, branch, path filters and SHA256. The CI audit checks a closed header:
only this branch's filtered pushes, Ubuntu 24.04, one job, five-minute ceiling,
read-only contents permission. Undeclared workflows, hash/header drift, mixed
registration, required-context reuse, and missing required jobs fail closed.
Existing required-check declarations, historical source evidence and remote
snapshot remain unchanged; no auxiliary config preserves the former behavior.
The registry is not a gate-disable switch or a source of live authority.

Review workflow changes and update its exact hash together. Do not create a PR
for this temporary evidence lane or treat its check as a required-check substitute.
The workflow checks out the validation commit separately from the fixed product.
It retains environment, build and per-case raw evidence on failure as well as
success; a failed candidate is preserved and not automatically restarted.

The inert actor has a six-second lifetime. Normal wrapper walltime is ten
seconds; one timeout case uses one second. Compiler execution uses a private
session and GNU timeout's thirty-second process-group KILL ceiling, with a
thirty-five-second outer wait and bounded orphan reaping. Unexpected escaped or
unreaped compiler children are unresolved failures, never PASS. Arbitrary daemon
escape and target PBS filesystem qualification are outside this synthetic scope.
