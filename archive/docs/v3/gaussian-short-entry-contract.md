# Auto-G16 Gaussian short entry and physical handoff

This is the offline implementation of `V31-GAUSSIAN-SHORT-ENTRY-01` and its
`PHYSICAL-HANDOFF-01` supplement. The frozen contract SHA-256 values are
`c9fb1bc15f541f30f6ef2aa1986e806aa00d903c97ce2a852adaf53c45b4a333`
and `3da5596688473887b55f1851da4f64017952cbc33f5aab723f965b0d0383890b`.
The later narrow
[`V31-GAUSSIAN-QSUB-FILE-CARRIER-01`](gaussian-qsub-file-carrier-contract.md)
supplement has frozen SHA-256
`ba7135e3b3b5595dad74bd6c3bba4ddf5a641580c48baf6a30412eceb23511e0` and
replaces only the carrier-through-qsub paragraphs below for newly qualified
bytes.
It does not qualify a target, install anything, authorize a live Attempt,
or change scientific acceptance. Previous Attempts remain immutable.

## Additive selection and review

The private builder requires the exact startup mode
`short-entry-physical-handoff-v1`, Gaussian completion mode and the new Q file.
There is no default conversion or historical fallback.

| Binding | New Gaussian tuple | Historical Gaussian tuple |
| --- | --- | --- |
| Spec adapter contract | 4 | 3 |
| Scheduler / rendering material / prebinding | 7 / 6 / 7 | 6 / 5 / 6 |
| Qualification / fixed deployment | 5 / 5 | 4 / 4 |
| Completion receipt schema and discriminator | 3 / 3, unchanged | 3 / 3 |

Snapshot/effect identities own the scientific GJF, exact short entry and exact
startup payload. New expanded reviews additionally disclose the five-stage
protocol, artifact caps and the uniquely derived config/submit-marker
descriptors. This disclosure is reconstructed from the snapshot and cannot
introduce operational authority. Missing or changed disclosure is stale;
historical expanded reviews retain their exact field set and identities.

The scheduler has one fixed qualified Python invocation and a 16 KiB cap.
A source-owned compressed loader keeps that invocation bounded. It contains
no caller-selected source, wrapper or config. The payload separately binds
canonical base64 envelopes for the qualified wrapper (64 KiB cap) and the
six-key config (6 MiB cap, canonical JSON without a final LF). The complete
payload is canonical JSON with exactly one LF and an 8 MiB cap.

## Physical authority order

The scientific input remains independently staged. The four additional
controls are ordered `gaussian.pbs`, `gaussian-startup.json`,
`gaussian-config.json`, `.auto-g16-v31-submit-intent`. Config comes only from
the reviewed payload envelope. The marker retains its historical two-key
snapshot/effect bytes. Every stage has durable Core and Transport receipts
before SUBMIT; neither SUBMIT nor the loader creates or adopts config.

The same mutation owner retains/rechecks all five files and the approved
Project/Attempt identity before publishing the immutable physical handoff.
The original record graph was strictly one-way:

`stages → handoff final/readback → pre-authority final/readback → carrier → one qsub → post receipt`

Pre-authority contains closed scope, approvals, predecessor, handoff and
fixed argv-template records. It never contains carrier bytes/hash, raw argv,
job/outcome or a post receipt. The loader reconstructs its ID from the verified
handoff and known resource template. That ID is never embedded back into the
entry. Post receipt records the actual argv/carrier and uncertainty after
invocation; interruption grants no retry authority.

For newly qualified file-carrier bytes, carrier transport and the qsub boundary
are governed by the supplement: an immutable Attempt-local canonical JSON file,
an immutable pre-call record, a direct qsub argv with neither `-v` nor `-V`, and
a `/2` post receipt. Existing Transport physical tokens remain canonical
standard-base64 typed JSON. Historical qualified bytes keep the original
environment-carrier parser and replay semantics.

## Retained loader and diagnostics

The loader pins original `.` and verifies the qualified interpreter,
handoff, submit marker and pre-authority before its first diagnostic marker.
It then verifies entry/payload/config through no-follow retained descriptors,
reconstructs snapshot/effect identities, compiles retained wrapper bytes and
provides exact config stdin in a fresh fixed namespace. It does not reopen
the verified control files or dispatch another shell. A renamed original cwd
can continue through its retained descriptor; the replacement tree is never
adopted. A replacement scheduler cwd is rejected.

The ordered stages are `entry-start`, `payload-verified`, `wrapper-handoff`,
`wrapper-entered`, `launch-lock-handoff`. Each uses a closed 13-field schema,
at most 4096 bytes, mode 0600, a previous-final SHA-256 chain, exclusive pending
creation, complete write/fsync, no-replace hard link, directory fsync and
identity/readback checks. Existing or partial files remain evidence and stop
publication. No cleanup or retry is performed.

The new wrapper only adds stage callbacks and retained cwd/marker plumbing.
Its direct-child status, subreaper/descendant wait, launch lock, receipt,
absence gate and output capture remain the existing completion protocol.
Stage markers and entry refusals never produce a Result or scientific success.

## Evidence and remaining gate

`tests/v31/transport/test_gaussian_short_entry.py` covers new schema,
physical replacement, retained execution, publication failure, acyclic
authority, single submission, native wire and compatibility boundaries using
temporary local objects and inert peers. Existing receipt grammar and
historical golden tests supply affected coverage. Task receipts map FC01–15,
GSE01–12 and PH01–16 to exact tests or unchanged-source evidence; selection is
recorded against the frozen Git candidate. Reused evidence is not a new run.

Q5 binds exact wrapper/probe/loader sources. The marker implementation is in
the loader digest; the native publisher is a separate exact source in the
profile basis. The controller pins the entry/payload renderer and all new
source modules. A future installation must verify those source digests against
its reviewed commit/tree, read back the fixed inventory and provide the new
delivery probe. An arbitrary Q commit/tree string is not source verification.

Exact target scheduler environment-byte fidelity (PH07), Linux publisher
behavior, qualification/deployment and one fresh fully approved Attempt remain
separately gated. Prior Gaussian or CREST delivery evidence cannot establish
those changed claims. This branch is not merge-ready without the governing
target evidence and Owner authority.
